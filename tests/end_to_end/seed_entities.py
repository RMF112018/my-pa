"""Seed Principal-scoped synthetic people the People browser suite needs.

The disposable e2e database has no entities after migrate-to-head. The page is
search and resolve, not a directory, so the harness inserts a uniquely named
person and two people who share a name — enough for a unique search hit and an
ambiguous resolve, and not a merge.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from sqlalchemy import create_engine

from my_pa.bootstrap.gateway import local_principal
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

WHEN = datetime(2026, 8, 22, 12, tzinfo=UTC)
PAT = "ent_e2ewp13pat000001"
ALEX_A = "ent_e2ewp13alex00001"
ALEX_B = "ent_e2ewp13alex00002"


def _person(entity_id: str, principal_id: str, display_name: str) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


def main() -> None:
    database_url = os.environ["MY_PA_DATABASE_URL"]
    principal_id = local_principal().principal_id
    with create_engine(database_url).begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(principal_id, _person(PAT, principal_id, "Pat Synthetic"))
        repository.create(principal_id, _person(ALEX_A, principal_id, "Alex Chen"))
        repository.create(principal_id, _person(ALEX_B, principal_id, "Alex Chen"))
        found = repository.search(principal_id, "Pat Synthetic", entity_type=EntityType.PERSON)
        if [row.entity_id for row in found] != [PAT]:
            raise RuntimeError("the unique synthetic person is not Principal-visible")
        shared = repository.search(principal_id, "Alex Chen", entity_type=EntityType.PERSON)
        if {row.entity_id for row in shared} != {ALEX_A, ALEX_B}:
            raise RuntimeError("the same-named synthetic people are not Principal-visible")


if __name__ == "__main__":
    main()
