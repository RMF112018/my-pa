"""Fixture-only WP-9 relationship ingestion and read use cases."""

from __future__ import annotations

from my_pa.contracts.ports import RelationshipRepository
from my_pa.domain.relationship.profile import OrganizationProfile, PersonProfile
from my_pa.domain.relationship.provider import PersonalSourceProvider

__all__ = ["RelationshipService"]


class RelationshipService:
    """Coordinate the read-only provider and governed identity repository."""

    def ingest_fixture_observations(
        self, provider: PersonalSourceProvider, repository: RelationshipRepository
    ) -> int:
        return sum(
            repository.record_observations(batch.domain, batch.observations)
            for batch in provider.observations()
        )

    def profile(self, repository: RelationshipRepository, person_id: str) -> PersonProfile | None:
        return repository.profile(
            person_id,
            expected_domains=("calendar", "contacts", "email"),
        )

    def organization_profile(
        self, repository: RelationshipRepository, organization_id: str
    ) -> OrganizationProfile | None:
        return repository.organization_profile(organization_id)
