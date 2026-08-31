"""A synthetic independent-consultant and multi-affiliation case, against real PostgreSQL.

RI-ENT-WP-05, `ENTITY-PERSON-001`. Follows
`tests/database/test_entity_names_tbr_gs4_studios_fixture.py`'s conventions
exactly: every name and identifier below is synthetic, invented for this file.
Nothing here is drawn from, derived from, or shaped to reproduce any real TBR
register content, or any real person -- the case patterns (an independent
consultant with no employer, and a person whose affiliation history moves
between two organizations) are the audit's own description of a *class* of
record the schema must represent, not an import of real data (`MIGRATION-001`,
`AGENTS.md` section 5).

**What this fixture proves:**

1. a synthetic independent consultant -- a person entity with **no**
   organization -- holds a project participation
   (`entity_project_participations`, RI-ENT-WP-04) *and* an affiliation record
   (`entity_person_organization_affiliations`, RI-ENT-WP-05) with
   `organization_entity_id IS NULL` and
   `affiliation_type_code = 'independent_consultant'`;
2. no placeholder or sentinel organization entity was ever created as a side
   effect of representing that consultant -- proved by asserting the exact
   organization-entity count in the fixture's Principal scope equals the
   number of *real* organizations this fixture deliberately created, no more;
3. a second synthetic person accumulates two affiliation rows over time -- a
   closed past affiliation (a non-null `effective_to`) to one organization,
   and an open-ended current one (`effective_to IS NULL`) to a different
   organization -- and querying for "current" via `effective_to IS NULL`
   returns exactly one unambiguous row.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

DISPOSABLE_DATABASE: Final = "my_pa_person_organization_affiliations_tbr_fixture_test"

PRINCIPAL: Final = "prn_hhhh0011hhhh0011hhhh0011"

#: The synthetic independent consultant: no organization at all.
CONSULTANT: Final = "ent_hhhh0011hhhh0011"
#: The synthetic project the consultant participates in directly.
PROJECT: Final = "ent_iiii0012iiii0012"

#: The synthetic person with an affiliation history spanning two employers.
CAREER_PERSON: Final = "ent_jjjj0013jjjj0013"
#: The one real organization the consultant's project cites as owner --
#: unrelated to the consultant, included only so "no placeholder organization"
#: is a meaningful assertion rather than a vacuous one over zero organizations.
OWNER_ORGANIZATION: Final = "ent_kkkk0014kkkk0014"
#: The two real organizations in the career person's history.
FORMER_EMPLOYER: Final = "ent_llll0015llll0015"
CURRENT_EMPLOYER: Final = "ent_mmmm0016mmmm0016"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
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


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _seed_entity(connection: object, entity_id: str, entity_type: str, name: str) -> None:
    connection.execute(  # type: ignore[attr-defined]
        text(
            f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
            "(entity_id, principal_id, entity_type, canonical_name, display_name, status) "
            "VALUES (:entity_id, :principal_id, :entity_type, :canonical, :display, 'active')"
        ),
        {
            "entity_id": entity_id,
            "principal_id": PRINCIPAL,
            "entity_type": entity_type,
            "canonical": name.lower(),
            "display": name,
        },
    )


@pytest.mark.database
def test_an_independent_consultant_holds_no_organization_and_no_placeholder_is_created(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        # --- the entities: one synthetic person, one synthetic project, one
        # synthetic (unrelated) owner organization -- the only REAL
        # organization this test deliberately creates -------------------------
        _seed_entity(connection, CONSULTANT, "person", "Synthetic Consultant Rivera")
        _seed_entity(connection, PROJECT, "project", "Synthetic Fictitious Commons")
        _seed_entity(
            connection, OWNER_ORGANIZATION, "organization", "Synthetic Fictitious Holdings"
        )

        # --- the consultant participates directly in the project, with no
        # organization in between (RI-ENT-WP-04) --------------------------------
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_project_participations "  # noqa: S608
                "(participation_id, principal_id, project_entity_id, participant_entity_id, "
                "project_display_name, role_code, role_basis_code, stakeholder_side_code, "
                "stakeholder_class_code, relationship_status_code) VALUES "
                "('eppt_hhhh0011hhhh0011', :principal_id, :project_entity_id, "
                ":participant_entity_id, 'Synthetic Consultant Rivera', 'CONSULTANT', "
                "'contractual', 'consultant', 'core', 'active')"
            ),
            {
                "principal_id": PRINCIPAL,
                "project_entity_id": PROJECT,
                "participant_entity_id": CONSULTANT,
            },
        )

        # --- the affiliation record itself: organization_entity_id IS NULL,
        # affiliation_type_code = independent_consultant -- never a
        # fabricated placeholder organization -----------------------------------
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_person_organization_affiliations "  # noqa: S608
                "(affiliation_id, principal_id, person_entity_id, organization_entity_id, "
                "job_title, affiliation_type_code) VALUES "
                "('poaf_hhhh0011hhhh0011', :principal_id, :person_entity_id, NULL, "
                "'Independent Consultant', 'independent_consultant')"
            ),
            {"principal_id": PRINCIPAL, "person_entity_id": CONSULTANT},
        )

    with migrated_engine.connect() as connection:
        # The affiliation row has no organization.
        affiliation = connection.execute(
            text(
                f"SELECT organization_entity_id, affiliation_type_code FROM "  # noqa: S608
                f"{SCHEMA}.entity_person_organization_affiliations "
                "WHERE person_entity_id = :person_entity_id"
            ),
            {"person_entity_id": CONSULTANT},
        ).one()
        assert affiliation == (None, "independent_consultant")

        # The project participation exists and names the consultant directly.
        participation = connection.execute(
            text(
                f"SELECT participant_entity_id FROM "  # noqa: S608
                f"{SCHEMA}.entity_project_participations WHERE project_entity_id = :project_id"
            ),
            {"project_id": PROJECT},
        ).scalar_one()
        assert participation == CONSULTANT

        # The proof that matters: exactly one organization entity exists in
        # this Principal's scope, and it is the one this test deliberately
        # created for the project's owner -- never a placeholder minted to
        # satisfy the affiliation's (nullable) organization_entity_id.
        organization_count = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entities "  # noqa: S608
                "WHERE entity_type = 'organization' AND principal_id = :principal_id"
            ),
            {"principal_id": PRINCIPAL},
        ).scalar_one()
        assert organization_count == 1
        only_organization = connection.execute(
            text(
                f"SELECT entity_id FROM {SCHEMA}.entities "  # noqa: S608
                "WHERE entity_type = 'organization' AND principal_id = :principal_id"
            ),
            {"principal_id": PRINCIPAL},
        ).scalar_one()
        assert only_organization == OWNER_ORGANIZATION


@pytest.mark.database
def test_two_affiliations_over_time_resolve_to_exactly_one_current_row(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _seed_entity(connection, CAREER_PERSON, "person", "Synthetic Analyst Okafor")
        _seed_entity(connection, FORMER_EMPLOYER, "organization", "Synthetic Former Employer LLC")
        _seed_entity(connection, CURRENT_EMPLOYER, "organization", "Synthetic Current Employer LLC")

        # A closed, historical affiliation: non-null effective_to.
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_person_organization_affiliations "  # noqa: S608
                "(affiliation_id, principal_id, person_entity_id, organization_entity_id, "
                "job_title, affiliation_type_code, effective_from, effective_to) VALUES "
                "('poaf_jjjj0013jjjj0013', :principal_id, :person_entity_id, "
                ":former_employer, 'Junior Analyst', 'employment', "
                "'2018-01-01', '2021-12-31')"
            ),
            {
                "principal_id": PRINCIPAL,
                "person_entity_id": CAREER_PERSON,
                "former_employer": FORMER_EMPLOYER,
            },
        )
        # The open-ended, current affiliation: effective_to IS NULL.
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_person_organization_affiliations "  # noqa: S608
                "(affiliation_id, principal_id, person_entity_id, organization_entity_id, "
                "job_title, affiliation_type_code, effective_from) VALUES "
                "('poaf_kkkk0014kkkk0014', :principal_id, :person_entity_id, "
                ":current_employer, 'Senior Analyst', 'employment', '2022-01-01')"
            ),
            {
                "principal_id": PRINCIPAL,
                "person_entity_id": CAREER_PERSON,
                "current_employer": CURRENT_EMPLOYER,
            },
        )

    with migrated_engine.connect() as connection:
        # The full history: two rows, to two different organizations.
        history = connection.execute(
            text(
                f"SELECT organization_entity_id, effective_to FROM "  # noqa: S608
                f"{SCHEMA}.entity_person_organization_affiliations "
                "WHERE person_entity_id = :person_entity_id ORDER BY effective_from"
            ),
            {"person_entity_id": CAREER_PERSON},
        ).all()
        assert len(history) == 2
        assert {row[0] for row in history} == {FORMER_EMPLOYER, CURRENT_EMPLOYER}

        # "Current" via effective_to IS NULL: exactly one unambiguous row.
        current = connection.execute(
            text(
                f"SELECT organization_entity_id, job_title FROM "  # noqa: S608
                f"{SCHEMA}.entity_person_organization_affiliations "
                "WHERE person_entity_id = :person_entity_id "
                "AND state = 'active' AND effective_to IS NULL"
            ),
            {"person_entity_id": CAREER_PERSON},
        ).all()
        assert len(current) == 1
        assert current[0] == (CURRENT_EMPLOYER, "Senior Analyst")
