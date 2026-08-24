"""WP-9 identity and read-model invariants without persistence."""

from __future__ import annotations

import ast
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

import pytest

from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.relationship import identity as identity_models
from my_pa.domain.relationship.identity import (
    IdentityObservation,
    IdentityResolutionError,
    UnresolvedMention,
)
from my_pa.domain.relationship.profile import (
    CoverageDomain,
    PersonProfile,
    ProfileIndicator,
    ProfileIndicatorBasis,
    ProfileIndicatorName,
    RelationshipFreshness,
)
from my_pa.infrastructure.persistence.tables import METADATA

WHEN = datetime(2026, 8, 4, 12, tzinfo=UTC)
OBSERVATION_ID = "iobs_0000000000000001"


def test_source_observation_has_no_canonical_person_link() -> None:
    observation = IdentityObservation(
        observation_id=OBSERVATION_ID,
        source_id="src_0000000000000001",
        source_object_id="obj_0000000000000001",
        source_version="ver_0000000000000001",
        observed_at=WHEN,
        display_name="Synthetic Person",
    )
    assert observation.display_name == "Synthetic Person"
    assert "person_id" not in {field.name for field in fields(IdentityObservation)}


def test_profile_coverage_fails_closed_unless_it_names_the_exact_observation_set() -> None:
    with pytest.raises(ValueError, match="exact observation set"):
        PersonProfile(
            person_id="per_0000000000000001",
            display_name="Synthetic Person",
            observation_ids=(OBSERVATION_ID,),
            coverage=(
                CoverageDomain(
                    domain="contacts",
                    state=CoverageState.UNAVAILABLE,
                    observation_ids=(),
                    observed_at=None,
                    as_of=WHEN,
                    freshness=RelationshipFreshness.UNAVAILABLE,
                    limitation="not supplied",
                ),
            ),
            evidence=(),
            timeline=(),
        )


def test_unavailable_is_never_an_empty_processed_domain() -> None:
    with pytest.raises(ValueError, match="search completed"):
        CoverageDomain(
            domain="calendar",
            state=CoverageState.PROCESSED,
            observation_ids=(),
            observed_at=None,
            as_of=WHEN,
            freshness=RelationshipFreshness.UNKNOWN,
        )


def test_successful_zero_result_is_explicit_and_does_not_claim_freshness() -> None:
    coverage = CoverageDomain(
        domain="calendar",
        state=CoverageState.PROCESSED,
        observation_ids=(),
        observed_at=WHEN,
        as_of=WHEN,
        freshness=RelationshipFreshness.UNKNOWN,
        zero_result_basis="synthetic fixture domain was searched successfully",
    )
    assert coverage.observation_ids == ()
    assert coverage.freshness is RelationshipFreshness.UNKNOWN


def test_indicator_requires_a_basis_and_time_window() -> None:
    with pytest.raises(ValueError, match="closed observable calculation basis"):
        ProfileIndicator(
            name=ProfileIndicatorName.INTERACTION_COUNT,
            value=2,
            calculation_basis="",  # type: ignore[arg-type]
            window_start=WHEN,
            window_end=WHEN,
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("relationship_health_score", 95),
        ("affinity_index", 8),
        ("protected_religion", "synthetic-faith"),
    ],
)
def test_indicator_generic_channel_rejects_scores_and_sensitive_traits(
    name: str, value: object
) -> None:
    with pytest.raises(ValueError, match="closed semantic name"):
        ProfileIndicator(
            name=name,  # type: ignore[arg-type]
            value=value,  # type: ignore[arg-type]
            calculation_basis=ProfileIndicatorBasis.SOURCE_OBSERVATION_COUNT,
            window_start=WHEN,
            window_end=WHEN,
        )


@pytest.mark.parametrize("value", [-1, 2_147_483_648, True, "3", "protected_religion"])
def test_interaction_count_has_a_typed_bounded_value(value: object) -> None:
    with pytest.raises(ValueError, match="bounded non-negative integer"):
        ProfileIndicator(
            name=ProfileIndicatorName.INTERACTION_COUNT,
            value=value,  # type: ignore[arg-type]
            calculation_basis=ProfileIndicatorBasis.SOURCE_OBSERVATION_COUNT,
            window_start=WHEN,
            window_end=WHEN,
        )


def test_unresolved_source_binding_is_bounded_without_storing_raw_mention_text() -> None:
    with pytest.raises(IdentityResolutionError, match="bounded"):
        UnresolvedMention(
            unresolved_mention_id="umen_0000000000000001",
            source_object_id="obj_0000000000000001",
            source_version="x" * 73,
            observed_at=WHEN,
        )
    assert "raw_text" not in {field.name for field in fields(UnresolvedMention)}


#: The table-name prefixes that make a table part of the relationship surface.
#: `relationship_` is the WP-9 substrate; `entities`/`entity_` is the
#: generalized entity plane. Both are frozen here rather than assumed, so a
#: plane added under a third prefix is undiscovered surface the count assertion
#: below reports rather than surface the scan silently omits.
RELATIONSHIP_TABLE_PREFIXES = ("relationship_", "entities", "entity_")

EXPECTED_MODEL_FIELDS = {
    "my_pa.domain.relationship.event.RelationshipEvent": frozenset(
        {
            "event_id",
            "principal_id",
            "person_id",
            "event_type",
            "occurred_at",
            "created_at",
            "context",
            "accepted",
            "source_ref",
        }
    ),
    "my_pa.domain.relationship.identity.Affiliation": frozenset(
        {
            "affiliation_id",
            "person_id",
            "organization_id",
            "observation_id",
            "role",
            "effective_from",
            "effective_to",
        }
    ),
    "my_pa.domain.relationship.identity.Alias": frozenset(
        {"alias_id", "person_id", "value", "observation_id"}
    ),
    "my_pa.domain.relationship.identity.DuplicateCandidateSet": frozenset(
        {"candidate_set_id", "person_ids", "observation_ids", "created_at"}
    ),
    "my_pa.domain.relationship.identity.IdentityCandidateSet": frozenset(
        {"candidate_set_id", "person_ids", "observation_ids", "created_at"}
    ),
    "my_pa.domain.relationship.identity.IdentityObservation": frozenset(
        {
            "observation_id",
            "source_id",
            "source_object_id",
            "source_version",
            "observed_at",
            "display_name",
        }
    ),
    "my_pa.domain.relationship.identity.IdentityResolution": frozenset(
        {
            "resolution_id",
            "action",
            "review_case_id",
            "decision_id",
            "retained_person_id",
            "prior_person_id",
            "observation_ids",
            "decided_at",
        }
    ),
    "my_pa.domain.relationship.identity.Organization": frozenset(
        {"organization_id", "display_name", "created_at"}
    ),
    "my_pa.domain.relationship.identity.Person": frozenset(
        {"person_id", "display_name", "created_at", "superseded_by_person_id"}
    ),
    "my_pa.domain.relationship.identity.UnresolvedMention": frozenset(
        {"unresolved_mention_id", "source_object_id", "source_version", "observed_at"}
    ),
    "my_pa.domain.relationship.profile.CoverageDomain": frozenset(
        {
            "domain",
            "state",
            "observation_ids",
            "observed_at",
            "as_of",
            "freshness",
            "limitation",
            "zero_result_basis",
        }
    ),
    "my_pa.domain.relationship.profile.EvidenceItem": frozenset(
        {"evidence_id", "authority", "observation_ids", "effective_at", "recorded_at"}
    ),
    "my_pa.domain.relationship.profile.OrganizationProfile": frozenset(
        {"organization_id", "display_name", "affiliations", "observation_ids"}
    ),
    "my_pa.domain.relationship.profile.PersonProfile": frozenset(
        {
            "person_id",
            "display_name",
            "observation_ids",
            "coverage",
            "evidence",
            "timeline",
            "aliases",
            "indicators",
            "completeness_claimed",
        }
    ),
    "my_pa.domain.relationship.profile.ProfileIndicator": frozenset(
        {"name", "value", "calculation_basis", "window_start", "window_end"}
    ),
    "my_pa.domain.relationship.profile.TimelineItem": frozenset(
        {"timeline_item_id", "person_id", "occurred_at", "observation_ids", "authority"}
    ),
    "my_pa.domain.relationship.provider.PersonalSourceBatch": frozenset(
        {"domain", "state", "observations", "limitation"}
    ),
    # The generalized entity plane. Frozen here on the same terms as the WP-9
    # models above: a field added to any of these without editing this constant
    # reddens the build, which is what makes the semantic deny rule in
    # `tests/architecture/test_relationship_scoring_surface_is_denied` a check
    # on a visible surface rather than on whatever happened to be declared.
    "my_pa.domain.relationship.entity.Entity": frozenset(
        {
            "entity_id",
            "principal_id",
            "entity_type",
            "canonical_name",
            "display_name",
            "status",
            "created_at",
            "updated_at",
            "version",
            "superseded_by_entity_id",
            "archived_from_status",
        }
    ),
    "my_pa.domain.relationship.entity.ExternalIdentifier": frozenset(
        {
            "identifier_id",
            "entity_id",
            "namespace",
            "normalized_value",
            "display_value",
            "principal_id",
            "verified",
            "effective_from",
            "effective_to",
            "state",
            "version",
            "updated_at",
            "retired_at",
            "superseded_by_identifier_id",
        }
    ),
    "my_pa.domain.relationship.entity.EntityAlias": frozenset(
        {
            "alias_id",
            "entity_id",
            "alias_type",
            "normalized_value",
            "display_value",
            "principal_id",
            "effective_from",
            "effective_to",
            "state",
            "version",
            "updated_at",
            "retired_at",
            "superseded_by_alias_id",
        }
    ),
    "my_pa.domain.relationship.entity.Assignment": frozenset(
        {
            "assignment_id",
            "entity_id",
            "assignment_type",
            "principal_id",
            "scope_entity_id",
            "role",
            "discipline",
            "responsibility_class",
            "effective_from",
            "effective_to",
            "state",
            "version",
            "updated_at",
            "ended_at",
            "superseded_by_assignment_id",
        }
    ),
    "my_pa.domain.relationship.entity.EntityRelationship": frozenset(
        {
            "relationship_id",
            "from_entity_id",
            "relationship_type",
            "to_entity_id",
            "principal_id",
            "scope_entity_id",
            "effective_from",
            "effective_to",
            "state",
            "version",
            "updated_at",
            "ended_at",
            "superseded_by_relationship_id",
        }
    ),
    # What a resolution attempt answers. Frozen here for a reason the durable
    # records above do not have: these are the types a caller reads to decide
    # whether two references name one person, so a field added to them is a new
    # input to that decision and has to be argued for rather than appear.
    "my_pa.domain.relationship.resolution.ResolutionEvidence": frozenset(
        {"basis", "matched_value", "verified", "source_record_id"}
    ),
    "my_pa.domain.relationship.resolution.ResolutionCandidate": frozenset(
        {
            "entity_id",
            "entity_type",
            "display_name",
            "status",
            "evidence",
            "superseded_by_entity_id",
            "signals",
        }
    ),
    # WP-RI-06: the governance records. Frozen here for the reason the
    # resolution types are: these decide *whether* an entity changes, so a field
    # added to one is a new input to that decision.
    "my_pa.domain.relationship.governance.EntityObservation": frozenset(
        {
            "observation_id",
            "principal_id",
            "kind",
            "observed_value",
            "normalized_value",
            "mention_display_name",
            "source_id",
            "source_object_id",
            "source_version_id",
            "observed_at",
            "recorded_at",
            "entity_id",
            "authority",
            "state",
            "state_reason",
            "superseded_by_observation_id",
            "resolution_version",
        }
    ),
    "my_pa.domain.relationship.governance.EntityProposal": frozenset(
        {
            "proposal_id",
            "principal_id",
            "kind",
            "state",
            "payload",
            "observation_ids",
            "proposed_at",
            "proposed_by",
            "decided_by",
            "decided_at",
            "decision_reason",
        }
    ),
    "my_pa.domain.relationship.governance.EntityMergeRecord": frozenset(
        {
            "merge_id",
            "principal_id",
            "retained_entity_id",
            "merged_entity_id",
            "proposal_id",
            "decided_by",
            "reason",
            "decided_at",
        }
    ),
    # WP-RI-A-04: the three ledger records, frozen here for the reason the
    # governance records above are. `EntityFactEvidenceLink` is the one that
    # matters most: it is the table that carries negative identity evidence, so
    # a field added to it is a new input to whether a pairing is proposed again.
    "my_pa.domain.relationship.governance.EntityMutationEvent": frozenset(
        {
            "event_id",
            "principal_id",
            "capability",
            "record_family",
            "record_id",
            "prior_version",
            "new_version",
            "authority",
            "before_state",
            "after_state",
            "reason",
            "idempotency_key",
            "request_digest",
            "correlation_id",
            "audit_id",
            "receipt_id",
            "actor_class",
            "recorded_at",
        }
    ),
    "my_pa.domain.relationship.governance.EntityFactEvidenceLink": frozenset(
        {
            "link_id",
            "principal_id",
            "entity_id",
            "identifier_id",
            "alias_id",
            "assignment_id",
            "relationship_id",
            "entity_observation_id",
            "capture_span_id",
            "knowledge_id",
            "role",
            "authority",
            "created_at",
        }
    ),
    "my_pa.domain.relationship.governance.EntityResolutionDecision": frozenset(
        {
            "decision_id",
            "principal_id",
            "observation_id",
            "sequence",
            "expected_resolution_version",
            "disposition",
            "entity_id",
            "reason",
            "evidence_link_ids",
            "decided_by",
            "actor_class",
            "review_case_id",
            "correlation_id",
            "audit_id",
            "receipt_id",
            "decided_at",
        }
    ),
    "my_pa.domain.relationship.context_card.ContextCardCoverage": frozenset(
        {"source_id", "observation_count", "most_recent_observation_at"}
    ),
    "my_pa.domain.relationship.context_card.EntityContextCard": frozenset(
        {
            "entity",
            "assembled_at",
            "aliases",
            "identifiers",
            "assignments",
            "relationships",
            "observations",
            "coverage",
            "limitations",
            "memories",
        }
    ),
    "my_pa.domain.relationship.resolution.EntityResolution": frozenset(
        {"outcome", "candidates", "warnings", "candidates_were_truncated"}
    ),
    "my_pa.domain.relationship.context_card.ContextCardMemory": frozenset(
        {
            "memory",
            "current_version",
        }
    ),
    "my_pa.domain.relationship.memory.MemoryAdmission": frozenset(
        {
            "receipt",
            "created",
        }
    ),
    "my_pa.domain.relationship.memory.MemoryContextLink": frozenset(
        {
            "context_link_id",
            "memory_version_id",
            "principal_id",
            "target_type",
            "target_id",
            "role",
            "authority",
            "created_at",
        }
    ),
    "my_pa.domain.relationship.memory.MemoryEvidenceLink": frozenset(
        {
            "evidence_link_id",
            "memory_version_id",
            "principal_id",
            "role",
            "created_at",
            "entity_observation_id",
            "capture_span_id",
            "knowledge_id",
        }
    ),
    "my_pa.domain.relationship.memory.MemoryProposalEvidence": frozenset(
        {
            "proposal_evidence_id",
            "memory_proposal_id",
            "principal_id",
            "role",
            "created_at",
            "entity_observation_id",
            "capture_span_id",
            "knowledge_id",
        }
    ),
    "my_pa.domain.relationship.memory.MemoryReceipt": frozenset(
        {
            "memory_id",
            "memory_version_id",
            "version_number",
            "aggregate_version",
            "lifecycle_state",
            "idempotency_key",
            "statement_sha256",
            "issued_at",
            "created",
        }
    ),
    "my_pa.domain.relationship.memory.RelationshipMemory": frozenset(
        {
            "memory_id",
            "principal_id",
            "subject_entity_id",
            "memory_kind",
            "lifecycle_state",
            "current_version_id",
            "current_version_number",
            "version",
            "pinned",
            "created_at",
            "updated_at",
            "archived_at",
        }
    ),
    "my_pa.domain.relationship.memory.RelationshipMemoryProposal": frozenset(
        {
            "memory_proposal_id",
            "principal_id",
            "subject_entity_id",
            "proposed_kind",
            "proposed_statement",
            "proposed_statement_sha256",
            "state",
            "method",
            "method_version",
            "classification",
            "proposed_at",
            "structured_value",
            "model_id",
            "model_version",
            "review_case_id",
            "accepted_memory_id",
            "accepted_memory_version_id",
            "invalidated_reason",
        }
    ),
    # No `statement` and no `risk_class`, and both absences are load-bearing.
    # The proposed text is withheld from the review listing on purpose (see
    # `application.service._review_case_payload`), and `risk_class` is a
    # property over a module constant because a dataclass field carrying the
    # token `risk` is refused by the scoring deny rule next door.
    "my_pa.domain.relationship.memory.RelationshipMemoryReviewCase": frozenset(
        {
            "review_case_id",
            "proposal_id",
            "subject_entity_id",
            "principal_id",
            "proposed_kind",
            "opened_at",
            "proposal_state",
            "review_version",
            "latest_disposition",
            "accepted_memory_id",
            "accepted_memory_version_id",
        }
    ),
    "my_pa.domain.relationship.memory.RelationshipMemoryVersion": frozenset(
        {
            "memory_version_id",
            "memory_id",
            "principal_id",
            "version_number",
            "statement",
            "statement_sha256",
            "memory_kind",
            "authority",
            "classification",
            "created_by_actor",
            "recorded_at",
            "idempotency_key",
            "correlation_id",
            "structured_value",
            "cloud_eligible",
            "observed_at",
            "effective_from",
            "effective_to",
            "prior_version_id",
            "correction_reason",
            "proposal_id",
            "review_case_id",
        }
    ),
}

EXPECTED_TABLE_COLUMNS = {
    "relationship_events": frozenset(
        {
            "event_id",
            "principal_id",
            "person_id",
            "event_type",
            "occurred_at",
            "created_at",
            "context",
            "accepted",
            "source_ref",
        }
    ),
    "relationship_affiliations": frozenset(
        {
            "affiliation_id",
            "principal_id",
            "person_id",
            "organization_id",
            "observation_id",
            "role",
            "effective_from",
            "effective_to",
        }
    ),
    "relationship_aliases": frozenset(
        {"alias_id", "principal_id", "person_id", "observation_id", "value"}
    ),
    "relationship_conversation_observations": frozenset(
        {"participant_id", "principal_id", "observation_id"}
    ),
    "relationship_conversation_participants": frozenset(
        {"participant_id", "principal_id", "conversation_id", "person_id", "unresolved_mention_id"}
    ),
    "relationship_duplicate_members": frozenset(
        {"duplicate_set_id", "principal_id", "person_id", "observation_id"}
    ),
    "relationship_duplicate_sets": frozenset(
        {"duplicate_set_id", "principal_id", "candidate_kind", "created_at"}
    ),
    "relationship_evidence": frozenset(
        {"evidence_id", "principal_id", "person_id", "authority", "effective_at", "recorded_at"}
    ),
    "relationship_evidence_observations": frozenset(
        {"evidence_id", "principal_id", "observation_id"}
    ),
    "relationship_identity_observations": frozenset(
        {
            "observation_id",
            "principal_id",
            "source_id",
            "source_object_id",
            "source_version",
            "source_domain",
            "display_name",
            "observed_at",
        }
    ),
    "relationship_identity_resolutions": frozenset(
        {
            "resolution_id",
            "principal_id",
            "resolution_sequence",
            "action",
            "review_case_id",
            "decision_id",
            "retained_person_id",
            "prior_person_id",
            "decided_at",
        }
    ),
    "relationship_identity_review_cases": frozenset(
        {
            "review_case_id",
            "principal_id",
            "duplicate_set_id",
            "requested_action",
            "retained_person_id",
            "prior_person_id",
            "opened_at",
        }
    ),
    "relationship_identity_review_decisions": frozenset(
        {"decision_id", "review_case_id", "sequence", "disposition", "principal_id", "decided_at"}
    ),
    "relationship_observation_links": frozenset(
        {"observation_id", "principal_id", "person_id", "resolution_id"}
    ),
    "relationship_organizations": frozenset(
        {"organization_id", "principal_id", "display_name", "created_at"}
    ),
    "relationship_people": frozenset(
        {
            "person_id",
            "principal_id",
            "display_name",
            "created_at",
            "superseded_by_person_id",
            "state_resolution_id",
        }
    ),
    "relationship_resolution_observations": frozenset(
        {"resolution_id", "principal_id", "observation_id"}
    ),
    "relationship_unresolved_mentions": frozenset(
        {
            "unresolved_mention_id",
            "principal_id",
            "source_object_id",
            "source_version",
            "observed_at",
        }
    ),
    "entities": frozenset(
        {
            "entity_id",
            "principal_id",
            "entity_type",
            "canonical_name",
            "display_name",
            "status",
            "created_at",
            "updated_at",
            "version",
            "superseded_by_entity_id",
            "archived_from_status",
        }
    ),
    "entity_external_identifiers": frozenset(
        {
            "identifier_id",
            "entity_id",
            "namespace",
            "normalized_value",
            "display_value",
            "verified",
            "effective_from",
            "effective_to",
            "principal_id",
            "state",
            "version",
            "updated_at",
            "retired_at",
            "superseded_by_identifier_id",
        }
    ),
    "entity_observations": frozenset(
        {
            "observation_id",
            "principal_id",
            "kind",
            "observed_value",
            "normalized_value",
            "mention_display_name",
            "source_id",
            "source_object_id",
            "source_version_id",
            "observed_at",
            "recorded_at",
            "entity_id",
            "authority",
            "state",
            "state_reason",
            "superseded_by_observation_id",
            "resolution_version",
        }
    ),
    "entity_proposals": frozenset(
        {
            "proposal_id",
            "principal_id",
            "kind",
            "state",
            "payload",
            "observation_ids",
            "proposed_at",
            "proposed_by",
            "decided_by",
            "decided_at",
            "decision_reason",
        }
    ),
    "entity_merge_records": frozenset(
        {
            "merge_id",
            "principal_id",
            "retained_entity_id",
            "merged_entity_id",
            "proposal_id",
            "decided_by",
            "reason",
            "decided_at",
        }
    ),
    "entity_aliases": frozenset(
        {
            "alias_id",
            "entity_id",
            "alias_type",
            "normalized_value",
            "display_value",
            "effective_from",
            "effective_to",
            "principal_id",
            "state",
            "version",
            "updated_at",
            "retired_at",
            "superseded_by_alias_id",
        }
    ),
    "entity_assignments": frozenset(
        {
            "assignment_id",
            "entity_id",
            "scope_entity_id",
            "assignment_type",
            "role",
            "discipline",
            "responsibility_class",
            "effective_from",
            "effective_to",
            "state",
            "principal_id",
            "version",
            "updated_at",
            "ended_at",
            "superseded_by_assignment_id",
        }
    ),
    "entity_mutation_events": frozenset(
        {
            "event_id",
            "principal_id",
            "capability",
            "record_family",
            "record_id",
            "prior_version",
            "new_version",
            "authority",
            "before_state",
            "after_state",
            "reason",
            "idempotency_key",
            "request_digest",
            "correlation_id",
            "audit_id",
            "receipt_id",
            "actor_class",
            "recorded_at",
        }
    ),
    "entity_fact_evidence_links": frozenset(
        {
            "link_id",
            "principal_id",
            "entity_id",
            "identifier_id",
            "alias_id",
            "assignment_id",
            "relationship_id",
            "entity_observation_id",
            "capture_span_id",
            "knowledge_id",
            "role",
            "authority",
            "created_at",
        }
    ),
    "entity_resolution_decisions": frozenset(
        {
            "decision_id",
            "principal_id",
            "observation_id",
            "sequence",
            "expected_resolution_version",
            "disposition",
            "entity_id",
            "reason",
            "evidence_link_ids",
            "decided_by",
            "actor_class",
            "review_case_id",
            "correlation_id",
            "audit_id",
            "receipt_id",
            "decided_at",
        }
    ),
    "entity_relationships": frozenset(
        {
            "relationship_id",
            "from_entity_id",
            "to_entity_id",
            "relationship_type",
            "scope_entity_id",
            "effective_from",
            "effective_to",
            "state",
            "version",
            "principal_id",
            "updated_at",
            "ended_at",
            "superseded_by_relationship_id",
        }
    ),
    "relationship_memories": frozenset(
        {
            "memory_id",
            "principal_id",
            "subject_entity_id",
            "memory_kind",
            "lifecycle_state",
            "current_version_id",
            "current_version_number",
            "version",
            "pinned",
            "created_at",
            "updated_at",
            "archived_at",
        }
    ),
    "relationship_memory_context_links": frozenset(
        {
            "context_link_id",
            "memory_version_id",
            "principal_id",
            "target_type",
            "target_id",
            "role",
            "authority",
            "created_at",
        }
    ),
    "relationship_memory_evidence_links": frozenset(
        {
            "evidence_link_id",
            "memory_version_id",
            "principal_id",
            "role",
            "entity_observation_id",
            "capture_span_id",
            "knowledge_id",
            "created_at",
        }
    ),
    "relationship_memory_proposal_evidence": frozenset(
        {
            "proposal_evidence_id",
            "memory_proposal_id",
            "principal_id",
            "role",
            "entity_observation_id",
            "capture_span_id",
            "knowledge_id",
            "created_at",
        }
    ),
    "relationship_memory_proposals": frozenset(
        {
            "memory_proposal_id",
            "principal_id",
            "subject_entity_id",
            "proposed_kind",
            "proposed_statement",
            "proposed_statement_sha256",
            "structured_value",
            "state",
            "method",
            "method_version",
            "model_id",
            "model_version",
            "classification",
            "proposed_at",
            "review_case_id",
            "accepted_memory_id",
            "accepted_memory_version_id",
            "invalidated_reason",
        }
    ),
    "relationship_memory_review_decisions": frozenset(
        {
            "decision_id",
            "memory_proposal_id",
            "review_case_id",
            "principal_id",
            "sequence",
            "disposition",
            "corrected_statement",
            "correlation_id",
            "audit_id",
            "decided_at",
        }
    ),
    "relationship_memory_submissions": frozenset(
        {
            "submission_id",
            "idempotency_key",
            "principal_id",
            "correlation_id",
            "operation",
            "payload_sha256",
            "server_received_at",
            "memory_id",
            "memory_version_id",
            "aggregate_version",
            "lifecycle_state",
        }
    ),
    "relationship_memory_versions": frozenset(
        {
            "memory_version_id",
            "memory_id",
            "principal_id",
            "version_number",
            "statement_text",
            "statement_sha256",
            "structured_value",
            "memory_kind",
            "authority",
            "classification",
            "cloud_eligible",
            "created_by_actor",
            "observed_at",
            "effective_from",
            "effective_to",
            "recorded_at",
            "prior_version_id",
            "correction_reason",
            "proposal_id",
            "review_case_id",
            "idempotency_key",
            "correlation_id",
        }
    ),
}


def _assert_closed_vocabulary(
    actual: dict[str, frozenset[str]], expected: dict[str, frozenset[str]]
) -> None:
    assert actual == expected, "unexpected relationship fields or undiscovered relationship surface"


def test_relationship_models_and_tables_have_a_closed_field_vocabulary() -> None:
    assert identity_models.__file__ is not None
    relationship_package = Path(identity_models.__file__).parent
    modules = tuple(
        import_module(f"my_pa.domain.relationship.{path.stem}")
        for path in sorted(relationship_package.glob("*.py"))
        if path.stem != "__init__"
    )
    models = {
        f"{value.__module__}.{value.__name__}": value
        for module in modules
        for value in vars(module).values()
        if isinstance(value, type)
        and is_dataclass(value)
        and value.__module__.startswith("my_pa.domain.relationship")
    }
    actual_model_fields = {
        name: frozenset(field.name for field in fields(model)) for name, model in models.items()
    }
    actual_table_columns = {
        table.name: frozenset(column.name for column in table.columns)
        for table in METADATA.tables.values()
        if table.name.startswith(RELATIONSHIP_TABLE_PREFIXES)
    }
    assert len(actual_model_fields) == 43
    assert len(actual_table_columns) == 37
    ast_dataclasses = {
        f"my_pa.domain.relationship.{path.stem}.{node.name}"
        for path in sorted(relationship_package.glob("*.py"))
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ClassDef)
        and any(
            (isinstance(decorator, ast.Name) and decorator.id == "dataclass")
            or (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
                and decorator.func.id == "dataclass"
            )
            for decorator in node.decorator_list
        )
    }
    assert ast_dataclasses == set(actual_model_fields)
    tables_module = import_module("my_pa.infrastructure.persistence.tables")
    assert tables_module.__file__ is not None
    table_tree = ast.parse(Path(tables_module.__file__).read_text())
    ast_relationship_tables = {
        target.id
        for node in ast.walk(table_tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "Table"
        for target in node.targets
        if isinstance(target, ast.Name) and target.id.startswith(RELATIONSHIP_TABLE_PREFIXES)
    }
    assert ast_relationship_tables == set(actual_table_columns)
    _assert_closed_vocabulary(actual_model_fields, EXPECTED_MODEL_FIELDS)
    _assert_closed_vocabulary(actual_table_columns, EXPECTED_TABLE_COLUMNS)


@pytest.mark.parametrize("surface", ["model", "table"])
def test_a_new_euphemistic_relationship_field_reddens_the_closed_vocabulary(
    surface: str,
) -> None:
    expected = EXPECTED_MODEL_FIELDS if surface == "model" else EXPECTED_TABLE_COLUMNS
    actual = dict(expected)
    target = next(iter(actual))
    actual[target] = actual[target] | {"affinity_index"}
    with pytest.raises(AssertionError, match="unexpected relationship fields"):
        _assert_closed_vocabulary(actual, expected)
