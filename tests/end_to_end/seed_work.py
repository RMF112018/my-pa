"""Seed only the Principal-scoped reference row the Work browser suite needs.

The browser must select a verified Person before it can create a Commitment.
An empty database migrated to head correctly contains no such Person, so the
real-stack harness inserts one synthetic, Principal-bound option before the
gateway starts.  No Task, Commitment, evidence record, or expected outcome is
seeded; those are all created through the browser/BFF during the tests.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from sqlalchemy import create_engine

from my_pa.bootstrap.gateway import local_principal
from my_pa.domain.relationship.identity import (
    IdentityCandidateSet,
    IdentityObservation,
    IdentityResolution,
    ResolutionAction,
)
from my_pa.infrastructure.persistence.commitment_management import (
    SqlCommitmentManagementRepository,
)
from my_pa.infrastructure.persistence.relationships import SqlRelationshipRepository


def main() -> None:
    database_url = os.environ["MY_PA_DATABASE_URL"]
    principal_id = local_principal().principal_id
    observed_at = datetime(2026, 8, 22, 12, tzinfo=UTC)
    observation = IdentityObservation(
        observation_id="iobs_e2e000000000001",
        source_id="src_e2e000000000001",
        source_object_id="obj_e2e000000000001",
        source_version="e2e-v1",
        observed_at=observed_at,
        display_name="E2E Synthetic Counterparty",
    )
    with create_engine(database_url).begin() as connection:
        repository = SqlRelationshipRepository(connection, principal_id=principal_id)
        repository.record_observations("contacts", (observation,))
        candidate = IdentityCandidateSet(
            candidate_set_id="dups_e2e000000000001",
            person_ids=(),
            observation_ids=(observation.observation_id,),
            created_at=observed_at,
        )
        review_id = repository.open_identity_review(
            candidate,
            ResolutionAction.LINK_OBSERVATION,
        )
        decision_id = repository.decide_identity_review(
            review_id,
            disposition="accept",
            principal_id=principal_id,
            decided_at=observed_at,
        )
        repository.apply_resolution(
            IdentityResolution(
                resolution_id="ires_e2e000000000001",
                action=ResolutionAction.LINK_OBSERVATION,
                review_case_id=review_id,
                decision_id=decision_id,
                retained_person_id="per_e2e000000000001",
                prior_person_id=None,
                observation_ids=(observation.observation_id,),
                decided_at=observed_at,
            ),
            display_name="E2E Synthetic Counterparty",
        )
        options = SqlCommitmentManagementRepository(connection).list_counterparties(
            principal_id,
            limit=2,
        )
        if [(option.person_id, option.display_name) for option in options] != [
            ("per_e2e000000000001", "E2E Synthetic Counterparty")
        ]:
            raise RuntimeError("the governed synthetic counterparty is not Principal-visible")


if __name__ == "__main__":
    main()
