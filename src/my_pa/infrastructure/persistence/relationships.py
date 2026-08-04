"""Governed relationship identity persistence and deterministic read models."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import cast

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from my_pa.contracts.ports import RelationshipRepository
from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.identity import (
    Alias,
    DuplicateCandidateSet,
    IdentityCandidateSet,
    IdentityObservation,
    IdentityResolution,
    IdentityResolutionError,
    ResolutionAction,
    UnresolvedMention,
)
from my_pa.domain.relationship.profile import (
    CoverageDomain,
    EvidenceAuthority,
    EvidenceItem,
    OrganizationProfile,
    PersonProfile,
    RelationshipFreshness,
    TimelineItem,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import (
    relationship_affiliations,
    relationship_aliases,
    relationship_conversation_observations,
    relationship_conversation_participants,
    relationship_duplicate_members,
    relationship_duplicate_sets,
    relationship_evidence,
    relationship_evidence_observations,
    relationship_identity_observations,
    relationship_identity_resolutions,
    relationship_identity_review_cases,
    relationship_identity_review_decisions,
    relationship_observation_links,
    relationship_organizations,
    relationship_people,
    relationship_resolution_observations,
    relationship_unresolved_mentions,
)

__all__ = ["SqlRelationshipRepository"]


def _alias_id(observation_id: str) -> str:
    return f"alias_{sha256(observation_id.encode()).hexdigest()[:32]}"


class SqlRelationshipRepository(RelationshipRepository):
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def record_observations(
        self, domain: str, observations: tuple[IdentityObservation, ...]
    ) -> int:
        if domain not in {"calendar", "contacts", "email"}:
            raise ValueError("a fixture observation has a known personal-source domain")
        count = 0
        for row in observations:
            existing = self._connection.execute(
                select(
                    relationship_identity_observations.c.observation_id,
                    relationship_identity_observations.c.source_domain,
                    relationship_identity_observations.c.display_name,
                    relationship_identity_observations.c.observed_at,
                ).where(
                    relationship_identity_observations.c.source_id == row.source_id,
                    relationship_identity_observations.c.source_object_id == row.source_object_id,
                    relationship_identity_observations.c.source_version == row.source_version,
                )
            ).one_or_none()
            if existing is not None:
                if tuple(existing) == (
                    row.observation_id,
                    domain,
                    row.display_name,
                    row.observed_at,
                ):
                    continue
                raise IdentityResolutionError(
                    "an observed source version cannot be rebound to another identity"
                )
            self._connection.execute(
                insert(relationship_identity_observations).values(
                    observation_id=row.observation_id,
                    source_id=row.source_id,
                    source_object_id=row.source_object_id,
                    source_version=row.source_version,
                    source_domain=domain,
                    display_name=row.display_name,
                    observed_at=row.observed_at,
                )
            )
            count += 1
        return count

    def open_identity_review(
        self,
        candidates: IdentityCandidateSet,
        action: ResolutionAction,
        *,
        retained_person_id: str | None = None,
        prior_person_id: str | None = None,
    ) -> str:
        if action in {ResolutionAction.MERGE_PERSON, ResolutionAction.SPLIT_PERSON} and (
            retained_person_id is None or prior_person_id is None
        ):
            raise IdentityResolutionError("a merge or split review names both canonical people")
        if action in {ResolutionAction.MERGE_PERSON, ResolutionAction.SPLIT_PERSON} and (
            retained_person_id == prior_person_id
            or set(candidates.person_ids) != {retained_person_id, prior_person_id}
        ):
            raise IdentityResolutionError(
                "a merge or split candidate set names exactly two reviewed people"
            )
        self._connection.execute(
            insert(relationship_duplicate_sets).values(
                duplicate_set_id=candidates.candidate_set_id,
                candidate_kind=(
                    "duplicate"
                    if isinstance(candidates, DuplicateCandidateSet)
                    else "identity_resolution"
                ),
                created_at=candidates.created_at,
            )
        )
        for person_id in candidates.person_ids:
            self._connection.execute(
                insert(relationship_duplicate_members).values(
                    duplicate_set_id=candidates.candidate_set_id, person_id=person_id
                )
            )
        for observation_id in candidates.observation_ids:
            self._connection.execute(
                insert(relationship_duplicate_members).values(
                    duplicate_set_id=candidates.candidate_set_id,
                    observation_id=observation_id,
                )
            )
        review_case_id = issue_identifier(IdKind.REVIEW_CASE)
        self._connection.execute(
            insert(relationship_identity_review_cases).values(
                review_case_id=review_case_id,
                duplicate_set_id=candidates.candidate_set_id,
                requested_action=action.value,
                retained_person_id=retained_person_id,
                prior_person_id=prior_person_id,
            )
        )
        return review_case_id

    def decide_identity_review(
        self,
        review_case_id: str,
        *,
        disposition: str,
        principal_id: str,
        decided_at: datetime,
    ) -> str:
        validate_identifier(review_case_id, IdKind.REVIEW_CASE)
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if disposition not in {"accept", "defer", "reject"}:
            raise IdentityResolutionError("an identity review disposition is known")
        sequence = (
            int(
                self._connection.execute(
                    select(func.count())
                    .select_from(relationship_identity_review_decisions)
                    .where(
                        relationship_identity_review_decisions.c.review_case_id == review_case_id
                    )
                ).scalar_one()
            )
            + 1
        )
        decision_id = issue_identifier(IdKind.REVIEW_DECISION)
        self._connection.execute(
            insert(relationship_identity_review_decisions).values(
                decision_id=decision_id,
                review_case_id=review_case_id,
                sequence=sequence,
                disposition=disposition,
                principal_id=principal_id,
                decided_at=decided_at,
            )
        )
        return decision_id

    def apply_resolution(self, resolution: IdentityResolution, *, display_name: str) -> None:
        existing = self._connection.execute(
            select(
                relationship_identity_resolutions.c.action,
                relationship_identity_resolutions.c.review_case_id,
                relationship_identity_resolutions.c.decision_id,
                relationship_identity_resolutions.c.retained_person_id,
                relationship_identity_resolutions.c.prior_person_id,
                relationship_identity_resolutions.c.decided_at,
            ).where(relationship_identity_resolutions.c.resolution_id == resolution.resolution_id)
        ).one_or_none()
        if existing is not None:
            stored_observations = tuple(
                str(value)
                for value in self._connection.execute(
                    select(relationship_resolution_observations.c.observation_id)
                    .where(
                        relationship_resolution_observations.c.resolution_id
                        == resolution.resolution_id
                    )
                    .order_by(relationship_resolution_observations.c.observation_id)
                ).scalars()
            )
            same_receipt = (
                existing.action == resolution.action.value
                and existing.review_case_id == resolution.review_case_id
                and existing.decision_id == resolution.decision_id
                and existing.retained_person_id == resolution.retained_person_id
                and existing.prior_person_id == resolution.prior_person_id
                and existing.decided_at == resolution.decided_at
                and stored_observations == tuple(sorted(resolution.observation_ids))
            )
            current_links = set(
                self._connection.execute(
                    select(relationship_observation_links.c.observation_id).where(
                        relationship_observation_links.c.resolution_id == resolution.resolution_id,
                        relationship_observation_links.c.person_id == resolution.retained_person_id,
                    )
                ).scalars()
            )
            state_receipt = self._connection.execute(
                select(relationship_people.c.state_resolution_id).where(
                    relationship_people.c.person_id
                    == (
                        resolution.prior_person_id
                        if resolution.action is ResolutionAction.MERGE_PERSON
                        else resolution.retained_person_id
                    )
                )
            ).scalar_one_or_none()
            if (
                same_receipt
                and current_links == set(resolution.observation_ids)
                and state_receipt == resolution.resolution_id
            ):
                return
            raise IdentityResolutionError("an identity resolution receipt is stale or conflicting")

        reviewed = self._connection.execute(
            select(
                relationship_identity_review_cases.c.requested_action,
                relationship_identity_review_cases.c.retained_person_id,
                relationship_identity_review_cases.c.prior_person_id,
                relationship_identity_review_decisions.c.disposition,
            )
            .join(
                relationship_identity_review_decisions,
                relationship_identity_review_decisions.c.review_case_id
                == relationship_identity_review_cases.c.review_case_id,
            )
            .where(
                relationship_identity_review_cases.c.review_case_id == resolution.review_case_id,
                relationship_identity_review_decisions.c.decision_id == resolution.decision_id,
                relationship_identity_review_decisions.c.sequence
                == select(func.max(relationship_identity_review_decisions.c.sequence))
                .where(
                    relationship_identity_review_decisions.c.review_case_id
                    == resolution.review_case_id
                )
                .scalar_subquery(),
            )
        ).one_or_none()
        if reviewed is None or reviewed.disposition != "accept":
            raise IdentityResolutionError("identity resolution requires its exact accepted review")
        if reviewed.requested_action != resolution.action.value:
            raise IdentityResolutionError("identity resolution must match the reviewed action")
        if resolution.action in {ResolutionAction.MERGE_PERSON, ResolutionAction.SPLIT_PERSON} and (
            reviewed.retained_person_id != resolution.retained_person_id
            or reviewed.prior_person_id != resolution.prior_person_id
        ):
            raise IdentityResolutionError("identity correction must match the reviewed people")
        candidate_people = {
            str(value)
            for value in self._connection.execute(
                select(relationship_duplicate_members.c.person_id)
                .join(
                    relationship_identity_review_cases,
                    relationship_identity_review_cases.c.duplicate_set_id
                    == relationship_duplicate_members.c.duplicate_set_id,
                )
                .where(
                    relationship_identity_review_cases.c.review_case_id
                    == resolution.review_case_id,
                    relationship_duplicate_members.c.person_id.is_not(None),
                )
            ).scalars()
        }
        if resolution.action in {ResolutionAction.MERGE_PERSON, ResolutionAction.SPLIT_PERSON} and (
            candidate_people != {resolution.retained_person_id, resolution.prior_person_id}
        ):
            raise IdentityResolutionError(
                "identity correction must match its exact reviewed candidate people"
            )
        candidate_observations = {
            str(value)
            for value in self._connection.execute(
                select(relationship_duplicate_members.c.observation_id)
                .join(
                    relationship_identity_review_cases,
                    relationship_identity_review_cases.c.duplicate_set_id
                    == relationship_duplicate_members.c.duplicate_set_id,
                )
                .where(
                    relationship_identity_review_cases.c.review_case_id
                    == resolution.review_case_id,
                    relationship_duplicate_members.c.observation_id.is_not(None),
                )
            ).scalars()
        }
        if candidate_observations != set(resolution.observation_ids):
            raise IdentityResolutionError(
                "identity resolution must match the reviewed observation set"
            )

        participant_ids_to_rebind: tuple[str, ...] = ()
        if resolution.action in {ResolutionAction.MERGE_PERSON, ResolutionAction.SPLIT_PERSON}:
            if resolution.prior_person_id is None:  # guarded by the domain model
                raise IdentityResolutionError("an identity correction names its prior person")
            participant_support_rows = self._connection.execute(
                select(
                    relationship_conversation_participants.c.participant_id,
                    relationship_conversation_participants.c.conversation_id,
                    relationship_conversation_observations.c.observation_id,
                )
                .join(
                    relationship_conversation_observations,
                    relationship_conversation_observations.c.participant_id
                    == relationship_conversation_participants.c.participant_id,
                )
                .where(
                    relationship_conversation_participants.c.person_id == resolution.prior_person_id
                )
            ).all()
            support_by_participant: dict[str, tuple[str, set[str]]] = {}
            for row in participant_support_rows:
                participant_id = str(row.participant_id)
                conversation_id = str(row.conversation_id)
                participant_entry = support_by_participant.setdefault(
                    participant_id, (conversation_id, set())
                )
                participant_entry[1].add(str(row.observation_id))
            affected = set(resolution.observation_ids)
            participants_to_rebind: list[str] = []
            for participant_id, (conversation_id, support) in support_by_participant.items():
                if not support.intersection(affected):
                    continue
                if not support.issubset(affected):
                    raise IdentityResolutionError(
                        "identity correction cannot leave ambiguous conversation support"
                    )
                collision = self._connection.execute(
                    select(relationship_conversation_participants.c.participant_id).where(
                        relationship_conversation_participants.c.conversation_id == conversation_id,
                        relationship_conversation_participants.c.person_id
                        == resolution.retained_person_id,
                    )
                ).scalar_one_or_none()
                if collision is not None:
                    raise IdentityResolutionError(
                        "identity correction cannot collapse distinct conversation participants"
                    )
                participants_to_rebind.append(participant_id)
            participant_ids_to_rebind = tuple(sorted(participants_to_rebind))

        if resolution.action is ResolutionAction.LINK_OBSERVATION:
            self._connection.execute(
                insert(relationship_people).values(
                    person_id=resolution.retained_person_id,
                    display_name=display_name,
                    created_at=resolution.decided_at,
                )
            )
        self._connection.execute(
            insert(relationship_identity_resolutions).values(
                resolution_id=resolution.resolution_id,
                action=resolution.action.value,
                review_case_id=resolution.review_case_id,
                decision_id=resolution.decision_id,
                retained_person_id=resolution.retained_person_id,
                prior_person_id=resolution.prior_person_id,
                decided_at=resolution.decided_at,
            )
        )
        if resolution.action is ResolutionAction.LINK_OBSERVATION:
            self._connection.execute(
                update(relationship_people)
                .where(relationship_people.c.person_id == resolution.retained_person_id)
                .values(state_resolution_id=resolution.resolution_id)
            )
        for observation_id in resolution.observation_ids:
            self._connection.execute(
                insert(relationship_resolution_observations).values(
                    resolution_id=resolution.resolution_id,
                    observation_id=observation_id,
                )
            )
            self._connection.execute(
                pg_insert(relationship_observation_links)
                .values(
                    observation_id=observation_id,
                    person_id=resolution.retained_person_id,
                    resolution_id=resolution.resolution_id,
                )
                .on_conflict_do_update(
                    index_elements=[relationship_observation_links.c.observation_id],
                    set_={
                        "person_id": resolution.retained_person_id,
                        "resolution_id": resolution.resolution_id,
                    },
                )
            )
            if resolution.action is ResolutionAction.LINK_OBSERVATION:
                alias_value = cast(
                    str | None,
                    self._connection.execute(
                        select(relationship_identity_observations.c.display_name).where(
                            relationship_identity_observations.c.observation_id == observation_id
                        )
                    ).scalar_one(),
                )
                if alias_value is not None and alias_value.strip():
                    self._connection.execute(
                        insert(relationship_aliases).values(
                            alias_id=_alias_id(observation_id),
                            person_id=resolution.retained_person_id,
                            observation_id=observation_id,
                            value=alias_value,
                        )
                    )
                evidence_id = f"source_{observation_id}"
                self._connection.execute(
                    pg_insert(relationship_evidence)
                    .values(
                        evidence_id=evidence_id,
                        person_id=resolution.retained_person_id,
                        authority=EvidenceAuthority.SOURCE_OBSERVATION.value,
                        recorded_at=resolution.decided_at,
                    )
                    .on_conflict_do_nothing(index_elements=[relationship_evidence.c.evidence_id])
                )
                self._connection.execute(
                    pg_insert(relationship_evidence_observations)
                    .values(evidence_id=evidence_id, observation_id=observation_id)
                    .on_conflict_do_nothing()
                )
        if resolution.action in {ResolutionAction.MERGE_PERSON, ResolutionAction.SPLIT_PERSON}:
            evidence_ids = select(relationship_evidence_observations.c.evidence_id).where(
                relationship_evidence_observations.c.observation_id.in_(resolution.observation_ids)
            )
            self._connection.execute(
                update(relationship_evidence)
                .where(relationship_evidence.c.evidence_id.in_(evidence_ids))
                .values(person_id=resolution.retained_person_id)
            )
            self._connection.execute(
                update(relationship_affiliations)
                .where(relationship_affiliations.c.observation_id.in_(resolution.observation_ids))
                .values(person_id=resolution.retained_person_id)
            )
            self._connection.execute(
                update(relationship_aliases)
                .where(relationship_aliases.c.observation_id.in_(resolution.observation_ids))
                .values(person_id=resolution.retained_person_id)
            )
            if participant_ids_to_rebind:
                self._connection.execute(
                    update(relationship_conversation_participants)
                    .where(
                        relationship_conversation_participants.c.participant_id.in_(
                            participant_ids_to_rebind
                        )
                    )
                    .values(person_id=resolution.retained_person_id)
                )
        if resolution.action is ResolutionAction.MERGE_PERSON:
            if resolution.prior_person_id is None:  # domain construction already refuses this
                raise IdentityResolutionError("a merge names its prior person")
            self._connection.execute(
                update(relationship_people)
                .where(relationship_people.c.person_id == resolution.prior_person_id)
                .values(
                    superseded_by_person_id=resolution.retained_person_id,
                    state_resolution_id=resolution.resolution_id,
                )
            )
        elif resolution.action is ResolutionAction.SPLIT_PERSON:
            if resolution.prior_person_id is None:  # domain construction already refuses this
                raise IdentityResolutionError("a split names its current person")
            self._connection.execute(
                update(relationship_people)
                .where(relationship_people.c.person_id == resolution.retained_person_id)
                .values(
                    superseded_by_person_id=None,
                    state_resolution_id=resolution.resolution_id,
                )
            )

    def direct_merge(self, retained_person_id: str, prior_person_id: str) -> None:
        validate_identifier(retained_person_id, IdKind.PERSON)
        validate_identifier(prior_person_id, IdKind.PERSON)
        raise IdentityResolutionError("direct identity merge is denied before persistence")

    def profile(self, person_id: str, *, expected_domains: tuple[str, ...]) -> PersonProfile | None:
        validate_identifier(person_id, IdKind.PERSON)
        person = self._connection.execute(
            select(
                relationship_people.c.display_name,
                relationship_people.c.state_resolution_id,
            ).where(
                relationship_people.c.person_id == person_id,
                relationship_people.c.superseded_by_person_id.is_(None),
            )
        ).one_or_none()
        if person is None:
            return None
        state_is_current = self._connection.execute(
            text(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM knowledge.relationship_identity_resolutions state
                  WHERE state.resolution_id = :state_resolution_id
                    AND state.retained_person_id = :person_id
                    AND (
                      (state.action = 'link_observation' AND NOT EXISTS (
                        SELECT 1
                        FROM knowledge.relationship_identity_resolutions correction
                        WHERE correction.action = 'merge_person'
                          AND correction.prior_person_id = :person_id
                      ))
                      OR
                      (state.action = 'split_person'
                       AND state.resolution_sequence = (
                         SELECT max(latest.resolution_sequence)
                         FROM knowledge.relationship_identity_resolutions latest
                         WHERE (latest.retained_person_id = state.retained_person_id
                                AND latest.prior_person_id = state.prior_person_id)
                            OR (latest.retained_person_id = state.prior_person_id
                                AND latest.prior_person_id = state.retained_person_id)
                       ))
                    )
                ) AND NOT EXISTS (
                  SELECT 1
                  FROM knowledge.relationship_observation_links link
                  JOIN knowledge.relationship_identity_resolutions receipt
                    ON receipt.resolution_id = link.resolution_id
                  WHERE link.person_id = :person_id
                    AND (
                      receipt.retained_person_id <> :person_id
                      OR receipt.resolution_sequence <> (
                        SELECT max(latest.resolution_sequence)
                        FROM knowledge.relationship_identity_resolutions latest
                        JOIN knowledge.relationship_resolution_observations latest_observation
                          ON latest_observation.resolution_id = latest.resolution_id
                        WHERE latest_observation.observation_id = link.observation_id
                      )
                    )
                )
                """
            ),
            {
                "person_id": person_id,
                "state_resolution_id": person.state_resolution_id,
            },
        ).scalar_one()
        if not state_is_current:
            raise IdentityResolutionError(
                "a relationship profile requires current canonical resolution state"
            )
        observations = self._connection.execute(
            select(
                relationship_identity_observations.c.observation_id,
                relationship_identity_observations.c.source_domain,
                relationship_identity_observations.c.observed_at,
            )
            .join(
                relationship_observation_links,
                relationship_observation_links.c.observation_id
                == relationship_identity_observations.c.observation_id,
            )
            .where(relationship_observation_links.c.person_id == person_id)
            .order_by(relationship_identity_observations.c.observation_id)
        ).all()
        observation_ids = tuple(str(row.observation_id) for row in observations)
        as_of = datetime.now(UTC)
        coverage = []
        for domain in expected_domains:
            domain_rows = [row for row in observations if row.source_domain == domain]
            coverage.append(
                CoverageDomain(
                    domain=domain,
                    state=(CoverageState.PROCESSED if domain_rows else CoverageState.UNAVAILABLE),
                    observation_ids=tuple(str(row.observation_id) for row in domain_rows),
                    observed_at=max((row.observed_at for row in domain_rows), default=None),
                    as_of=as_of,
                    freshness=(
                        RelationshipFreshness.UNKNOWN
                        if domain_rows
                        else RelationshipFreshness.UNAVAILABLE
                    ),
                    limitation=None if domain_rows else "no fixture observation was supplied",
                )
            )
        evidence_rows = self._connection.execute(
            select(
                relationship_evidence.c.evidence_id,
                relationship_evidence.c.authority,
                relationship_evidence.c.effective_at,
                relationship_evidence.c.recorded_at,
                relationship_evidence_observations.c.observation_id,
            )
            .outerjoin(
                relationship_evidence_observations,
                relationship_evidence_observations.c.evidence_id
                == relationship_evidence.c.evidence_id,
            )
            .where(relationship_evidence.c.person_id == person_id)
            .order_by(relationship_evidence.c.evidence_id)
        ).all()
        grouped: dict[
            str,
            list[tuple[str, datetime | None, datetime, str | None]],
        ] = {}
        for row in evidence_rows:
            grouped.setdefault(str(row.evidence_id), []).append(
                (
                    str(row.authority),
                    row.effective_at,
                    row.recorded_at,
                    str(row.observation_id) if row.observation_id is not None else None,
                )
            )
        evidence = tuple(
            EvidenceItem(
                evidence_id=evidence_id,
                authority=EvidenceAuthority(rows[0][0]),
                observation_ids=tuple(row[3] for row in rows if row[3] is not None),
                effective_at=rows[0][1],
                recorded_at=rows[0][2],
            )
            for evidence_id, rows in grouped.items()
        )
        timeline = tuple(
            TimelineItem(
                timeline_item_id=f"tli_{str(row.observation_id).removeprefix('iobs_')}",
                person_id=person_id,
                occurred_at=row.observed_at,
                observation_ids=(str(row.observation_id),),
                authority=EvidenceAuthority.SOURCE_OBSERVATION,
            )
            for row in observations
        )
        aliases = tuple(
            Alias(
                alias_id=str(row.alias_id),
                person_id=str(row.person_id),
                observation_id=str(row.observation_id),
                value=str(row.value),
            )
            for row in self._connection.execute(
                select(relationship_aliases)
                .where(relationship_aliases.c.person_id == person_id)
                .order_by(relationship_aliases.c.observation_id)
            )
        )
        return PersonProfile(
            person_id=person_id,
            display_name=str(person.display_name),
            observation_ids=observation_ids,
            coverage=tuple(coverage),
            evidence=evidence,
            timeline=timeline,
            aliases=aliases,
        )

    def organization_profile(self, organization_id: str) -> OrganizationProfile | None:
        validate_identifier(organization_id, IdKind.ORGANIZATION)
        organization = self._connection.execute(
            select(relationship_organizations.c.display_name).where(
                relationship_organizations.c.organization_id == organization_id
            )
        ).one_or_none()
        if organization is None:
            return None
        rows = self._connection.execute(
            select(
                relationship_affiliations.c.person_id,
                relationship_affiliations.c.role,
                relationship_affiliations.c.effective_from,
                relationship_affiliations.c.effective_to,
                relationship_affiliations.c.observation_id,
            )
            .where(relationship_affiliations.c.organization_id == organization_id)
            .order_by(
                relationship_affiliations.c.effective_from,
                relationship_affiliations.c.person_id,
            )
        ).all()
        return OrganizationProfile(
            organization_id=organization_id,
            display_name=str(organization.display_name),
            affiliations=tuple(
                (
                    str(row.person_id),
                    str(row.role) if row.role is not None else None,
                    row.effective_from,
                    row.effective_to,
                )
                for row in rows
            ),
            observation_ids=tuple(str(row.observation_id) for row in rows),
        )

    def record_source_affiliation(
        self,
        *,
        organization_id: str,
        organization_name: str,
        affiliation_id: str,
        person_id: str,
        observation_id: str,
        role: str | None,
        effective_from: datetime | None,
        effective_to: datetime | None,
    ) -> None:
        validate_identifier(organization_id, IdKind.ORGANIZATION)
        validate_identifier(affiliation_id, IdKind.AFFILIATION)
        validate_identifier(person_id, IdKind.PERSON)
        validate_identifier(observation_id, IdKind.IDENTITY_OBSERVATION)
        linked = self._connection.execute(
            select(relationship_observation_links.c.observation_id).where(
                relationship_observation_links.c.observation_id == observation_id,
                relationship_observation_links.c.person_id == person_id,
            )
        ).scalar_one_or_none()
        if linked is None:
            raise IdentityResolutionError(
                "an affiliation requires a governed, source-bound identity observation"
            )
        existing_name = self._connection.execute(
            select(relationship_organizations.c.display_name).where(
                relationship_organizations.c.organization_id == organization_id
            )
        ).scalar_one_or_none()
        if existing_name is not None and existing_name != organization_name:
            raise IdentityResolutionError(
                "an organization identifier cannot be rebound to another name"
            )
        if existing_name is None:
            self._connection.execute(
                insert(relationship_organizations).values(
                    organization_id=organization_id, display_name=organization_name
                )
            )
        self._connection.execute(
            insert(relationship_affiliations).values(
                affiliation_id=affiliation_id,
                person_id=person_id,
                organization_id=organization_id,
                observation_id=observation_id,
                role=role,
                effective_from=effective_from,
                effective_to=effective_to,
            )
        )

    def record_unresolved_mention(self, mention: UnresolvedMention) -> None:
        existing = self._connection.execute(
            select(
                relationship_unresolved_mentions.c.source_object_id,
                relationship_unresolved_mentions.c.source_version,
                relationship_unresolved_mentions.c.observed_at,
            ).where(
                relationship_unresolved_mentions.c.unresolved_mention_id
                == mention.unresolved_mention_id
            )
        ).one_or_none()
        if existing is not None:
            if tuple(existing) == (
                mention.source_object_id,
                mention.source_version,
                mention.observed_at,
            ):
                return
            raise IdentityResolutionError("an unresolved mention identifier cannot be rebound")
        self._connection.execute(
            insert(relationship_unresolved_mentions).values(
                unresolved_mention_id=mention.unresolved_mention_id,
                source_object_id=mention.source_object_id,
                source_version=mention.source_version,
                observed_at=mention.observed_at,
            )
        )

    def attach_conversation_participant(
        self,
        conversation_id: str,
        *,
        person_id: str | None = None,
        unresolved_mention_id: str | None = None,
        observation_ids: tuple[str, ...] = (),
    ) -> str:
        validate_identifier(conversation_id, IdKind.CONVERSATION)
        if (person_id is None) is (unresolved_mention_id is None):
            raise IdentityResolutionError("a conversation participant names exactly one target")
        if person_id is not None:
            validate_identifier(person_id, IdKind.PERSON)
        if unresolved_mention_id is not None:
            validate_identifier(unresolved_mention_id, IdKind.UNRESOLVED_MENTION)
        if len(observation_ids) > 200:
            raise IdentityResolutionError("conversation participant support is bounded")
        if len(observation_ids) != len(set(observation_ids)):
            raise IdentityResolutionError("conversation participant support contains no duplicates")
        for observation_id in observation_ids:
            validate_identifier(observation_id, IdKind.IDENTITY_OBSERVATION)
        requested_observations = set(observation_ids)
        if person_id is not None and requested_observations:
            linked_observations = {
                str(value)
                for value in self._connection.execute(
                    select(relationship_observation_links.c.observation_id).where(
                        relationship_observation_links.c.person_id == person_id,
                        relationship_observation_links.c.observation_id.in_(observation_ids),
                    )
                ).scalars()
            }
            if linked_observations != requested_observations:
                raise IdentityResolutionError(
                    "conversation support must currently identify its resolved participant"
                )
        if unresolved_mention_id is not None and requested_observations:
            mention = self._connection.execute(
                select(
                    relationship_unresolved_mentions.c.source_object_id,
                    relationship_unresolved_mentions.c.source_version,
                ).where(
                    relationship_unresolved_mentions.c.unresolved_mention_id
                    == unresolved_mention_id
                )
            ).one_or_none()
            if mention is None:
                raise IdentityResolutionError("conversation support names a recorded mention")
            matching_observations = {
                str(value)
                for value in self._connection.execute(
                    select(relationship_identity_observations.c.observation_id).where(
                        relationship_identity_observations.c.observation_id.in_(observation_ids),
                        relationship_identity_observations.c.source_object_id
                        == mention.source_object_id,
                        relationship_identity_observations.c.source_version
                        == mention.source_version,
                    )
                ).scalars()
            }
            if matching_observations != requested_observations:
                raise IdentityResolutionError(
                    "conversation support must match its unresolved source identity"
                )
        participant_id = issue_identifier(IdKind.CONVERSATION_PARTICIPANT)
        self._connection.execute(
            insert(relationship_conversation_participants).values(
                participant_id=participant_id,
                conversation_id=conversation_id,
                person_id=person_id,
                unresolved_mention_id=unresolved_mention_id,
            )
        )
        for observation_id in observation_ids:
            self._connection.execute(
                pg_insert(relationship_conversation_observations)
                .values(participant_id=participant_id, observation_id=observation_id)
                .on_conflict_do_nothing()
            )
        return participant_id
