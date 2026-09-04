"""A synthetic multi-project participation case, against real PostgreSQL.

RI-ENT-WP-04. This fixture is the TBR-shaped case the work package requires:
the campaign document's own project-participation record family exists
because a single organization or person routinely participates in more than
one project at once, under different roles and sometimes under different
project-facing presentations of its name, and because a source is sometimes
honestly unclear about what role a participant plays.

**Every name, project, and identifier below is entirely invented for this
test.** Nothing here is drawn from, derived from, or shaped to reproduce any
real register content -- not a project name, not a company name, not a
person's name -- on the same discipline
`tests/database/test_entity_names_tbr_gs4_studios_fixture.py` states for its
own synthetic case.

**What this fixture proves:**

1. one organization entity participates in TWO different projects,
   simultaneously active, under DIFFERENT roles and DIFFERENT project-facing
   display names -- and neither project-facing name alters the shared
   entity's own `display_name`/`canonical_name` (the boundary
   `test_project_entity_participation_isolation.py` also proves, exercised
   here in the two-project shape this fixture is actually about);
2. a third participant recorded with `role_basis_code = unresolved` and
   `role_code = NULL` -- the schema honestly recording "we don't know yet"
   rather than forcing a guess (RULING 3);
3. exactly the entities and participation rows this fixture describes exist
   -- no more, no fewer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

DISPOSABLE_DATABASE: Final = "my_pa_project_participation_multi_project_fixture_test"

PRINCIPAL: Final = "prn_kkkk0011kkkk0011kkkk0011"

#: Two synthetic projects, invented for this test.
PROJECT_MERIDIAN: Final = "ent_kkkk0011kkkk0011"
PROJECT_LARKSPUR: Final = "ent_llll0012llll0012"

#: The one organization that participates in BOTH projects at once, under
#: two different roles and two different project-facing presentations.
PARTICIPANT_BELLCREST: Final = "ent_mmmm0013mmmm0013"

#: A second, unrelated participant on the Larkspur project whose role basis
#: is honestly unresolved rather than guessed.
PARTICIPANT_UNRESOLVED: Final = "ent_nnnn0014nnnn0014"

PARTICIPATION_MERIDIAN: Final = "eppt_kkkk0011kkkk0011"
PARTICIPATION_LARKSPUR: Final = "eppt_llll0012llll0012"
PARTICIPATION_UNRESOLVED: Final = "eppt_mmmm0013mmmm0013"

#: Bellcrest's own global identity -- what `entities.display_name` says about
#: it independent of any project.
_BELLCREST_ENTITY_DISPLAY_NAME: Final = "Bellcrest Consulting Group"

#: The two DIFFERENT project-facing presentations Bellcrest trades under on
#: each project -- neither matches its own global identity above.
_BELLCREST_ON_MERIDIAN: Final = "Bellcrest Consulting (Meridian Point Team)"
_BELLCREST_ON_LARKSPUR: Final = "BCG Advisory Services"

_UNRESOLVED_ENTITY_DISPLAY_NAME: Final = "Fennimore Trades Collective"
_UNRESOLVED_ROLE_TEXT: Final = (
    "appears in project correspondence but the source never states what this "
    "party actually does on the project"
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.mark.database
def test_one_organization_participates_in_two_projects_under_different_roles_and_names(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        # --- the two projects and the shared participant -------------------
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                "(entity_id, principal_id, entity_type, canonical_name, display_name, status) "
                "VALUES "
                "(:meridian_id, :principal_id, 'project', 'meridian point redevelopment', "
                "'Meridian Point Redevelopment', 'active'), "
                "(:larkspur_id, :principal_id, 'project', 'larkspur commons', "
                "'Larkspur Commons', 'active'), "
                "(:bellcrest_id, :principal_id, 'organization', 'bellcrest consulting group', "
                ":bellcrest_display, 'active'), "
                "(:unresolved_id, :principal_id, 'organization', 'fennimore trades collective', "
                ":unresolved_display, 'active')"
            ),
            {
                "meridian_id": PROJECT_MERIDIAN,
                "larkspur_id": PROJECT_LARKSPUR,
                "bellcrest_id": PARTICIPANT_BELLCREST,
                "unresolved_id": PARTICIPANT_UNRESOLVED,
                "principal_id": PRINCIPAL,
                "bellcrest_display": _BELLCREST_ENTITY_DISPLAY_NAME,
                "unresolved_display": _UNRESOLVED_ENTITY_DISPLAY_NAME,
            },
        )

        # --- Bellcrest on Meridian Point: CONSULTANT, its own project name -
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_project_participations "  # noqa: S608
                "(participation_id, principal_id, project_entity_id, participant_entity_id, "
                "project_display_name, role_code, role_basis_code, stakeholder_side_code, "
                "stakeholder_class_code, relationship_status_code) VALUES "
                "(:participation_id, :principal_id, :project_id, :participant_id, "
                ":project_display_name, 'CONSULTANT', 'contractual', 'consultant', 'core', "
                "'active')"
            ),
            {
                "participation_id": PARTICIPATION_MERIDIAN,
                "principal_id": PRINCIPAL,
                "project_id": PROJECT_MERIDIAN,
                "participant_id": PARTICIPANT_BELLCREST,
                "project_display_name": _BELLCREST_ON_MERIDIAN,
            },
        )

        # --- Bellcrest on Larkspur Commons: a DIFFERENT role, a DIFFERENT
        # project-facing name, simultaneously active -----------------------
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_project_participations "  # noqa: S608
                "(participation_id, principal_id, project_entity_id, participant_entity_id, "
                "project_display_name, role_code, role_basis_code, stakeholder_side_code, "
                "stakeholder_class_code, relationship_status_code) VALUES "
                "(:participation_id, :principal_id, :project_id, :participant_id, "
                ":project_display_name, 'SUBCONTRACTOR', 'project_observed', 'contractor', "
                "'adjacent', 'active')"
            ),
            {
                "participation_id": PARTICIPATION_LARKSPUR,
                "principal_id": PRINCIPAL,
                "project_id": PROJECT_LARKSPUR,
                "participant_id": PARTICIPANT_BELLCREST,
                "project_display_name": _BELLCREST_ON_LARKSPUR,
            },
        )

        # --- the unresolved participant: role_code NULL, role_basis_code
        # 'unresolved' -- the schema recording "we don't know" honestly ----
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_project_participations "  # noqa: S608
                "(participation_id, principal_id, project_entity_id, participant_entity_id, "
                "project_display_name, role_code, role_text, role_basis_code, "
                "stakeholder_side_code, stakeholder_class_code, relationship_status_code) "
                "VALUES "
                "(:participation_id, :principal_id, :project_id, :participant_id, "
                ":project_display_name, NULL, :role_text, 'unresolved', 'other', 'unresolved', "
                "'unresolved')"
            ),
            {
                "participation_id": PARTICIPATION_UNRESOLVED,
                "principal_id": PRINCIPAL,
                "project_id": PROJECT_LARKSPUR,
                "participant_id": PARTICIPANT_UNRESOLVED,
                "project_display_name": _UNRESOLVED_ENTITY_DISPLAY_NAME,
                "role_text": _UNRESOLVED_ROLE_TEXT,
            },
        )

    with migrated_engine.connect() as connection:
        # --- exactly four entities: two projects, two participants --------
        entity_count = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entities WHERE principal_id = :principal_id"  # noqa: S608
            ),
            {"principal_id": PRINCIPAL},
        ).scalar_one()
        assert entity_count == 4

        # --- exactly three participation rows ------------------------------
        participation_count = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entity_project_participations "  # noqa: S608
                "WHERE principal_id = :principal_id"
            ),
            {"principal_id": PRINCIPAL},
        ).scalar_one()
        assert participation_count == 3

        # --- Bellcrest's two participations: different roles, different
        # project-facing names, both simultaneously active -----------------
        bellcrest_rows = connection.execute(
            text(
                f"SELECT project_entity_id, role_code, project_display_name, state "  # noqa: S608
                f"FROM {SCHEMA}.entity_project_participations "
                "WHERE participant_entity_id = :participant_id"
            ),
            {"participant_id": PARTICIPANT_BELLCREST},
        ).all()
        bellcrest_by_project = {row[0]: row for row in bellcrest_rows}
        assert set(bellcrest_by_project) == {PROJECT_MERIDIAN, PROJECT_LARKSPUR}

        meridian_row = bellcrest_by_project[PROJECT_MERIDIAN]
        assert meridian_row[1] == "CONSULTANT"
        assert meridian_row[2] == _BELLCREST_ON_MERIDIAN
        assert meridian_row[3] == "active"

        larkspur_row = bellcrest_by_project[PROJECT_LARKSPUR]
        assert larkspur_row[1] == "SUBCONTRACTOR"
        assert larkspur_row[2] == _BELLCREST_ON_LARKSPUR
        assert larkspur_row[3] == "active"

        assert meridian_row[2] != larkspur_row[2]
        assert meridian_row[1] != larkspur_row[1]

        # --- neither project-facing name altered the shared entity row ----
        entity_names = connection.execute(
            text(
                f"SELECT display_name, canonical_name FROM {SCHEMA}.entities "  # noqa: S608
                "WHERE entity_id = :entity_id"
            ),
            {"entity_id": PARTICIPANT_BELLCREST},
        ).one()
        assert entity_names[0] == _BELLCREST_ENTITY_DISPLAY_NAME
        assert entity_names[0] not in (_BELLCREST_ON_MERIDIAN, _BELLCREST_ON_LARKSPUR)
        assert entity_names[1] not in (
            _BELLCREST_ON_MERIDIAN.casefold(),
            _BELLCREST_ON_LARKSPUR.casefold(),
        )

        # --- the unresolved participant: role_code NULL, role_basis_code
        # 'unresolved', never a guessed role -------------------------------
        unresolved_row = connection.execute(
            text(
                f"SELECT role_code, role_basis_code, role_text, relationship_status_code "  # noqa: S608
                f"FROM {SCHEMA}.entity_project_participations "
                "WHERE participant_entity_id = :participant_id"
            ),
            {"participant_id": PARTICIPANT_UNRESOLVED},
        ).one()
        assert unresolved_row[0] is None
        assert unresolved_row[1] == "unresolved"
        assert unresolved_row[2] == _UNRESOLVED_ROLE_TEXT
        assert unresolved_row[3] == "unresolved"
