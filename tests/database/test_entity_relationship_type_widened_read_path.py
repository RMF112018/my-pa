"""`EntityRelationshipType` widened to 34 of 35 codes: the typed read path no
longer raises, except for one deliberately withheld code.

Clears the WP-08 blocker the campaign document recorded as "Second blocking
dependency... STILL STANDING" (`docs/campaign/ROBUST-ENTITY-DATA-MODEL-20260830.md`):
`entity_relationship_types` (RI-ENT-WP-06a, migration `8dc3619891bb`) has
always held 35 seeded codes, but until this revision the Python
`EntityRelationshipType` `StrEnum` (`src/my_pa/domain/relationship/entity.py`)
was frozen at the original fifteen, so `infrastructure.persistence.entity.
_row_to_relationship`'s `EntityRelationshipType(str(row.relationship_type))`
call raised `ValueError` for any of the twenty new codes.

This test proves the fix at the database, not by assumption: it writes one
real `knowledge.entity_relationships` row for **each of the nineteen new
codes now admitted** directly (a raw `INSERT`, the same way
`tests/database/test_entity_relationship_types_tbr_fixture.py` seeds corporate-
lineage edges -- bypassing the application command layer on purpose, since
what this test is proving is the *read* path, not the write path), then reads
each row back through `SqlEntityRepository.relationship`, which calls
`_row_to_relationship` internally. No `ValueError` is raised, and the
returned `EntityRelationship.relationship_type` equals the expected
`EntityRelationshipType` member.

**`design_coordinates_with` is the twentieth new code and is deliberately
NOT included above.** Adding it as an `EntityRelationshipType` member trips
`tests/architecture/test_relationship_scoring_surface_is_denied.py`'s
"location tracking" denial pattern (`latitude|longitude|geolocation|
coordinates|whereabouts|tracking`), which token-matches the substring
"coordinates" in its name/value even though the taxonomy entry means
design-discipline coordination between two project participants, not
geolocation. That guard file is not touched, weakened, or reasoned around by
this revision -- see `EntityRelationshipType`'s own docstring, "One code
deliberately withheld". `test_design_coordinates_with_is_withheld_and_still_
raises` below proves that gap is real and unchanged, not silently dropped.
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
from my_pa.domain.relationship.entity import EntityRelationshipType
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

DISPOSABLE_DATABASE: Final = "my_pa_entity_relationship_type_widened_read_path_test"

PRINCIPAL: Final = "prn_wwww0020wwww0020wwww0020"

FROM_ORG: Final = "ent_wwww0020wwww0020"
TO_ORG: Final = "ent_xxxx0021xxxx0021"

#: The nineteen of the twenty new codes `8dc3619891bb` seeded that this
#: revision actually admits as `EntityRelationshipType` members -- restated
#: here, verbatim, from the migration's own `_NEW_CODES` tuple
#: (`migrations/versions/20260831_8dc3619891bb_add_entity_relationship_types.py`),
#: minus `design_coordinates_with` (see `WITHHELD_CODE` below), not
#: re-derived from `EntityRelationshipType` itself, so this test cannot pass
#: merely because the enum and this list were built from the same typo.
NEW_CODES: Final[tuple[str, ...]] = (
    "brand_of",
    "operates_as",
    "dba_of",
    "historical_identity_of",
    "parent_of",
    "subsidiary_of",
    "acquired_by",
    "practice_of",
    "contracting_entity_for",
    "managed_by",
    "owner_representative_for",
    "project_controls_advisor_to",
    "technical_reviewer_of",
    "peer_reviewer_of",
    "utility_provider_for",
    "permitting_authority_for",
    "seller_developer_for",
    "sales_marketing_agent_for",
    "sequence_interfaces_with",
)

#: The one new code `8dc3619891bb` seeded that is deliberately NOT an
#: `EntityRelationshipType` member -- see the module docstring and
#: `EntityRelationshipType`'s own docstring, "One code deliberately
#: withheld".
WITHHELD_CODE: Final = "design_coordinates_with"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
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
    """The disposable database, upgraded to head and disposed afterwards."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def seeded_entities(migrated_engine: Engine) -> Engine:
    """Two synthetic organization entities, the endpoints every edge below reuses."""
    with migrated_engine.begin() as connection:
        for entity_id, canonical, display in (
            (FROM_ORG, "synthetic widened source org", "Synthetic Widened Source Org"),
            (TO_ORG, "synthetic widened target org", "Synthetic Widened Target Org"),
        ):
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                    "(entity_id, principal_id, entity_type, canonical_name, display_name, "
                    "status) VALUES (:entity_id, :principal_id, 'organization', :canonical, "
                    ":display, 'active')"
                ),
                {
                    "entity_id": entity_id,
                    "principal_id": PRINCIPAL,
                    "canonical": canonical,
                    "display": display,
                },
            )
    return migrated_engine


def _relationship_id(index: int) -> str:
    """A synthetic, valid `erel_` identifier unique per index (0-18), never
    derived from the code itself, so two codes can never collide on it.
    """
    return f"erel_new{index:02d}0000000000000000"


# --- the nineteen newly-admitted codes it must be true for -------------------


def test_the_nineteen_new_codes_are_all_members_of_the_widened_enum() -> None:
    """Guards the parametrization below: every code this test writes must be a
    real `EntityRelationshipType` member, or the parametrized test would be
    silently skipped rather than proving anything.
    """
    assert len(NEW_CODES) == 19
    assert len(set(NEW_CODES)) == 19
    for code in NEW_CODES:
        assert EntityRelationshipType(code).value == code


def test_the_nineteen_new_codes_are_disjoint_from_the_original_fifteen() -> None:
    original_fifteen = {
        "works_for",
        "reports_to",
        "represents",
        "manages",
        "leads",
        "responsible_for",
        "approver_for",
        "decision_maker_for",
        "primary_contact_for",
        "member_of",
        "consultant_to",
        "contractor_on",
        "subcontractor_to",
        "vendor_for",
        "affiliated_with",
    }
    assert original_fifteen.isdisjoint(NEW_CODES)
    assert original_fifteen | set(NEW_CODES) == {member.value for member in EntityRelationshipType}
    # `design_coordinates_with` is neither in the original fifteen nor in the
    # nineteen newly-admitted codes -- it is not a member of the enum at all.
    assert WITHHELD_CODE not in (original_fifteen | set(NEW_CODES))


def test_design_coordinates_with_is_withheld_and_still_raises() -> None:
    """The one code this revision deliberately does not admit.

    Proves the gap `EntityRelationshipType`'s own docstring discloses is
    real and current, not a stale claim: `design_coordinates_with` is not a
    member, so constructing it raises `ValueError` exactly as every one of
    the twenty new codes did before this revision.
    """
    assert WITHHELD_CODE not in {member.value for member in EntityRelationshipType}
    with pytest.raises(ValueError):
        EntityRelationshipType(WITHHELD_CODE)


@pytest.mark.parametrize("code", NEW_CODES)
def test_a_row_carrying_a_new_relationship_type_code_reads_back_through_row_to_relationship(
    seeded_entities: Engine, code: str
) -> None:
    """Writes one raw `entity_relationships` row for `code`, then reads it back
    through `SqlEntityRepository.relationship` -- which calls
    `_row_to_relationship`, the exact call site that used to raise
    `ValueError` for this code. No exception, and the typed field round-trips.
    """
    relationship_id = _relationship_id(NEW_CODES.index(code))
    with seeded_entities.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_relationships "  # noqa: S608
                "(relationship_id, from_entity_id, relationship_type, to_entity_id, "
                "principal_id) VALUES "
                "(:relationship_id, :from_entity_id, :relationship_type, :to_entity_id, "
                ":principal_id)"
            ),
            {
                "relationship_id": relationship_id,
                "from_entity_id": FROM_ORG,
                "relationship_type": code,
                "to_entity_id": TO_ORG,
                "principal_id": PRINCIPAL,
            },
        )

    with seeded_entities.connect() as connection:
        repository = SqlEntityRepository(connection)
        # This is the call under test: it fails with ValueError before the
        # enum is widened, for every one of these nineteen new codes
        # (design_coordinates_with excepted -- see WITHHELD_CODE above).
        relationship = repository.relationship(PRINCIPAL, relationship_id)

    assert relationship is not None
    assert relationship.relationship_type == EntityRelationshipType(code)
    assert relationship.relationship_type.value == code
    assert relationship.from_entity_id == FROM_ORG
    assert relationship.to_entity_id == TO_ORG


def test_all_nineteen_new_codes_also_read_back_through_the_paged_relationships_list(
    seeded_entities: Engine,
) -> None:
    """`SqlEntityRepository.relationships` (the paged, per-entity list) also
    calls `_row_to_relationship` for every row -- proven once, for all
    nineteen codes in one page, rather than assuming the single-row
    `relationship` accessor above is the only caller that matters.
    """
    with seeded_entities.begin() as connection:
        for index, code in enumerate(NEW_CODES):
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.entity_relationships "  # noqa: S608
                    "(relationship_id, from_entity_id, relationship_type, to_entity_id, "
                    "principal_id) VALUES "
                    "(:relationship_id, :from_entity_id, :relationship_type, :to_entity_id, "
                    ":principal_id)"
                ),
                {
                    "relationship_id": _relationship_id(index),
                    "from_entity_id": FROM_ORG,
                    "relationship_type": code,
                    "to_entity_id": TO_ORG,
                    "principal_id": PRINCIPAL,
                },
            )

    with seeded_entities.connect() as connection:
        repository = SqlEntityRepository(connection)
        relationships = repository.relationships(PRINCIPAL, FROM_ORG, direction="outgoing")

    assert {relationship.relationship_type.value for relationship in relationships} == set(
        NEW_CODES
    )
