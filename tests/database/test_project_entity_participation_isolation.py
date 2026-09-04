"""The `project_display_name` / `entities.display_name` boundary, proven end-to-end.

RI-ENT-WP-04. `EntityProjectParticipation`'s docstring calls this "the single
most important semantic boundary in this work package":
`project_display_name` is project-scoped fact, never global identity, and
nothing may ever copy it into `entities.display_name` or
`entities.canonical_name`, or the reverse.
`tests/unit/test_project_entity_participation_domain.py` proves the dataclass
carries no field that could do this; this file proves the same boundary holds
against a real PostgreSQL server -- writing a participation row never
disturbs the entity row it references, in either direction.

**Synthetic data only.** Every name and identifier below is invented for this
test and does not reproduce any real register content.

This is a narrower, single-purpose companion to
`tests/database/test_project_participation_synthetic_multi_project_fixture.py`,
which covers the multi-project/multi-role TBR-shaped scenario at greater
length; this file stays focused on the isolation proof alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

DISPOSABLE_DATABASE: Final = "my_pa_project_participation_isolation_test"

PRINCIPAL: Final = "prn_hhhh0007hhhh0007hhhh0007"
PROJECT_ONE: Final = "ent_hhhh0007hhhh0007"
PROJECT_TWO: Final = "ent_iiii0008iiii0008"
PARTICIPANT: Final = "ent_jjjj0009jjjj0009"

PARTICIPATION_ONE: Final = "eppt_hhhh0007hhhh0007"
PARTICIPATION_TWO: Final = "eppt_iiii0008iiii0008"

#: The entity's own global identity -- what `entities.display_name` and
#: `entities.canonical_name` say about it, independent of any project.
_ENTITY_DISPLAY_NAME: Final = "Ashford Structural Group"
_ENTITY_CANONICAL_NAME: Final = "ashford structural group"

#: Two DIFFERENT project-facing names for the SAME entity -- neither matches
#: the entity's own global identity above, which is the point.
_PROJECT_ONE_DISPLAY_NAME: Final = "Ashford SG (Meridian Point JV)"
_PROJECT_TWO_DISPLAY_NAME: Final = "ASG Structural Services"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _seed_entity(engine: Engine, entity_id: str, entity_type: str, name: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                "(entity_id, principal_id, entity_type, canonical_name, display_name, status) "
                "VALUES (:entity_id, :principal_id, :entity_type, :canonical, :display, 'active')"
            ),
            {
                "entity_id": entity_id,
                "principal_id": PRINCIPAL,
                "entity_type": entity_type,
                "canonical": name.casefold(),
                "display": name,
            },
        )


def _insert_participation(
    engine: Engine,
    *,
    participation_id: str,
    project_entity_id: str,
    project_display_name: str,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_project_participations "  # noqa: S608
                "(participation_id, principal_id, project_entity_id, participant_entity_id, "
                "project_display_name, role_basis_code, stakeholder_side_code, "
                "stakeholder_class_code, relationship_status_code) VALUES "
                "(:participation_id, :principal_id, :project_entity_id, :participant_entity_id, "
                ":project_display_name, 'contractual', 'contractor', 'core', 'active')"
            ),
            {
                "participation_id": participation_id,
                "principal_id": PRINCIPAL,
                "project_entity_id": project_entity_id,
                "participant_entity_id": PARTICIPANT,
                "project_display_name": project_display_name,
            },
        )


def _entity_names(engine: Engine, entity_id: str) -> tuple[str, str]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT display_name, canonical_name FROM {SCHEMA}.entities "  # noqa: S608
                "WHERE entity_id = :entity_id"
            ),
            {"entity_id": entity_id},
        ).one()
    return row[0], row[1]


@pytest.mark.database
def test_inserting_a_participation_never_touches_the_entitys_global_identity(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, PROJECT_ONE, "project", "Meridian Point Redevelopment")
    _seed_entity(migrated_engine, PARTICIPANT, "organization", _ENTITY_DISPLAY_NAME)

    display_before, canonical_before = _entity_names(migrated_engine, PARTICIPANT)
    assert display_before == _ENTITY_DISPLAY_NAME
    assert canonical_before == _ENTITY_CANONICAL_NAME

    _insert_participation(
        migrated_engine,
        participation_id=PARTICIPATION_ONE,
        project_entity_id=PROJECT_ONE,
        project_display_name=_PROJECT_ONE_DISPLAY_NAME,
    )

    display_after, canonical_after = _entity_names(migrated_engine, PARTICIPANT)
    assert display_after == display_before == _ENTITY_DISPLAY_NAME
    assert canonical_after == canonical_before == _ENTITY_CANONICAL_NAME
    assert display_after != _PROJECT_ONE_DISPLAY_NAME
    assert canonical_after != _PROJECT_ONE_DISPLAY_NAME.casefold()


@pytest.mark.database
def test_two_participations_of_the_same_participant_keep_independent_project_names(
    migrated_engine: Engine,
) -> None:
    """A second participation for the SAME participant on a DIFFERENT
    project, with a THIRD distinct project_display_name, persists
    independently -- neither project name leaks into the entity row nor into
    the other participation."""
    _seed_entity(migrated_engine, PROJECT_ONE, "project", "Meridian Point Redevelopment")
    _seed_entity(migrated_engine, PROJECT_TWO, "project", "Larkspur Commons")
    _seed_entity(migrated_engine, PARTICIPANT, "organization", _ENTITY_DISPLAY_NAME)

    _insert_participation(
        migrated_engine,
        participation_id=PARTICIPATION_ONE,
        project_entity_id=PROJECT_ONE,
        project_display_name=_PROJECT_ONE_DISPLAY_NAME,
    )
    _insert_participation(
        migrated_engine,
        participation_id=PARTICIPATION_TWO,
        project_entity_id=PROJECT_TWO,
        project_display_name=_PROJECT_TWO_DISPLAY_NAME,
    )

    with migrated_engine.connect() as connection:
        rows = dict(
            connection.execute(
                text(
                    f"SELECT participation_id, project_display_name FROM "  # noqa: S608
                    f"{SCHEMA}.entity_project_participations WHERE participant_entity_id = :pid"
                ),
                {"pid": PARTICIPANT},
            ).all()
        )
    assert rows[PARTICIPATION_ONE] == _PROJECT_ONE_DISPLAY_NAME
    assert rows[PARTICIPATION_TWO] == _PROJECT_TWO_DISPLAY_NAME
    assert rows[PARTICIPATION_ONE] != rows[PARTICIPATION_TWO]

    # Neither project-facing name leaked into the shared entity row.
    display_name, canonical_name = _entity_names(migrated_engine, PARTICIPANT)
    assert display_name == _ENTITY_DISPLAY_NAME
    assert canonical_name == _ENTITY_CANONICAL_NAME
    assert display_name not in (_PROJECT_ONE_DISPLAY_NAME, _PROJECT_TWO_DISPLAY_NAME)
