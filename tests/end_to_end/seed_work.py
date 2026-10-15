"""Seed only the Principal-scoped reference row the Work browser suite needs.

The browser must select a current counterparty Entity before it can create a
Commitment. An empty database migrated to head correctly contains no Entity, so
the real-stack harness inserts one synthetic, Principal-bound `person` Entity
before the gateway starts. No Task, Commitment, evidence record, or expected
outcome is seeded; those are all created through the browser/BFF during the
tests.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from sqlalchemy import create_engine, insert

from my_pa.bootstrap.gateway import local_principal
from my_pa.domain.relationship.entity import EntityStatus, EntityType
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.persistence.commitment_management import (
    SqlCommitmentManagementRepository,
)
from my_pa.infrastructure.persistence.tables import entities

COUNTERPARTY_ENTITY_ID = "ent_e2e000000000001"
COUNTERPARTY_DISPLAY_NAME = "E2E Synthetic Counterparty"


def main() -> None:
    database_url = os.environ["MY_PA_DATABASE_URL"]
    principal_id = local_principal().principal_id
    created_at = datetime(2026, 8, 22, 12, tzinfo=UTC)
    with create_engine(database_url).begin() as connection:
        connection.execute(
            insert(entities).values(
                entity_id=COUNTERPARTY_ENTITY_ID,
                principal_id=principal_id,
                entity_type=EntityType.PERSON.value,
                canonical_name=normalize_name(COUNTERPARTY_DISPLAY_NAME),
                display_name=COUNTERPARTY_DISPLAY_NAME,
                status=EntityStatus.ACTIVE.value,
                created_at=created_at,
                updated_at=created_at,
                version=1,
            )
        )
        options = SqlCommitmentManagementRepository(connection).list_counterparties(
            principal_id,
            limit=2,
        )
        if [(option.entity_id, option.display_name) for option in options] != [
            (COUNTERPARTY_ENTITY_ID, COUNTERPARTY_DISPLAY_NAME)
        ]:
            raise RuntimeError("the synthetic counterparty Entity is not Principal-visible")


if __name__ == "__main__":
    main()
