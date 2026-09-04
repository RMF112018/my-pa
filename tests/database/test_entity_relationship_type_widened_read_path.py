"""`EntityRelationshipType` widened to 35 of 35 codes: the typed read path no
longer raises for any seeded relationship-type code, and the enum and the
DB-level taxonomy are exact two-directional mirrors of each other.

Clears the WP-08 blocker the campaign document recorded as "Second blocking
dependency... STILL STANDING" (`docs/campaign/ROBUST-ENTITY-DATA-MODEL-20260830.md`):
`entity_relationship_types` (RI-ENT-WP-06a, migration `8dc3619891bb`) has
always held 35 seeded codes, but until a prior revision the Python
`EntityRelationshipType` `StrEnum` (`src/my_pa/domain/relationship/entity.py`)
was frozen at the original fifteen, so `infrastructure.persistence.entity.
_row_to_relationship`'s `EntityRelationshipType(str(row.relationship_type))`
call raised `ValueError` for any of the twenty new codes. A prior pass
widened the enum to nineteen of those twenty and disclosed the twentieth,
`design_coordinates_with`, as withheld -- adding it as a member tripped
`tests/architecture/test_relationship_scoring_surface_is_denied.py`'s
"location tracking" denial pattern (`latitude|longitude|geolocation|
coordinates|whereabouts|tracking`), which token-matches the substring
"coordinates" in its name/value even though the taxonomy entry means
design-discipline coordination between two project participants, not
geolocation.

**That gap is closed by this revision, by renaming the code rather than
touching the guard.** Migration `c99cd8ed8d1c` renamed the seeded
`entity_relationship_types` row from `design_coordinates_with` to
`design_coordination_with` (every other column unchanged -- a rename, not a
new taxonomy decision), and `EntityRelationshipType.DESIGN_COORDINATION_WITH`
is now the enum's thirty-fifth member. `design_coordination_with` tokenizes
to `("design", "coordination", "with")`, none of which `fullmatch` any
pattern in the guard's `DENIED` tuple -- see `EntityRelationshipType`'s own
docstring for the full verification. That guard file is not touched,
weakened, or reasoned around by this revision.

This test proves the fix at the database, not by assumption: it writes one
real `knowledge.entity_relationships` row for **every one of the thirty-five
seeded codes** directly (a raw `INSERT`, the same way
`tests/database/test_entity_relationship_types_tbr_fixture.py` seeds
corporate-lineage edges -- bypassing the application command layer on
purpose, since what this test proves is the *read* path, not the write
path), then reads each row back through `SqlEntityRepository.relationship`
(and, once more, through the paged `SqlEntityRepository.relationships`
accessor), which calls `_row_to_relationship` internally. No `ValueError` is
raised for any of the thirty-five, and each round-tripped
`EntityRelationship.relationship_type` equals the expected
`EntityRelationshipType` member -- covering both the fifteen original codes
and all twenty new ones, `design_coordination_with` included, not just the
nineteen a prior pass proved.

**Two-directional parity, not just "the enum has 35 members."** A dedicated
test below queries the live `entity_relationship_types` table's seeded codes
and asserts that set is *exactly* `{member.value for member in
EntityRelationshipType}`: no code in the table without a matching enum
member, and no enum member without a matching seeded table row. That is the
genuine parity check the enum's widening exists to establish -- a count
match alone (`len(EntityRelationshipType) == 35` and `SELECT count(*) ... ==
35`) would pass even if the two sets disagreed on which 35 values they held.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text

from my_pa.domain.relationship.entity import EntityRelationshipType
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

DISPOSABLE_DATABASE: Final = "my_pa_entity_relationship_type_widened_read_path_test"

PRINCIPAL: Final = "prn_wwww0020wwww0020wwww0020"

FROM_ORG: Final = "ent_wwww0020wwww0020"
TO_ORG: Final = "ent_xxxx0021xxxx0021"

#: The original fifteen `EntityRelationshipType` codes, restated (not
#: imported) so this list cannot silently drift from what `9def3c2e63bb`
#: first froze and `8dc3619891bb` seeded first -- the same discipline
#: `tests/schema/test_entity_relationship_types_migration.py`'s
#: `EXISTING_CODES` follows.
EXISTING_CODES: Final[tuple[str, ...]] = (
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
)

#: The twenty codes `8dc3619891bb` added, restated here verbatim from the
#: migration's own `_NEW_CODES` tuple except for `design_coordination_with`,
#: which is restated under the name migration `c99cd8ed8d1c` renamed it to --
#: not re-derived from `EntityRelationshipType` itself, so this test cannot
#: pass merely because the enum and this list were built from the same typo.
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
    "design_coordination_with",
    "utility_provider_for",
    "permitting_authority_for",
    "seller_developer_for",
    "sales_marketing_agent_for",
    "sequence_interfaces_with",
)

#: All thirty-five seeded codes, existing plus new -- the full population
#: this revision's round-trip proof covers, not just the twenty new ones.
ALL_35_CODES: Final[tuple[str, ...]] = EXISTING_CODES + NEW_CODES


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


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
    """A synthetic, valid `erel_` identifier unique per index (0-34), never
    derived from the code itself, so two codes can never collide on it.
    """
    return f"erel_all{index:02d}00000000000000000"


# --- the enum and the seed data agree on the population ----------------------


def test_all_35_codes_are_members_of_the_widened_enum() -> None:
    """Guards the parametrization below: every code this test writes must be a
    real `EntityRelationshipType` member, or the parametrized test would be
    silently skipped rather than proving anything.
    """
    assert len(ALL_35_CODES) == 35
    assert len(set(ALL_35_CODES)) == 35
    for code in ALL_35_CODES:
        assert EntityRelationshipType(code).value == code


def test_the_thirty_five_codes_are_exactly_the_enums_members() -> None:
    assert set(EXISTING_CODES).isdisjoint(NEW_CODES)
    assert set(ALL_35_CODES) == {member.value for member in EntityRelationshipType}
    assert len(EntityRelationshipType) == 35


# --- every one of the thirty-five codes reads back cleanly -------------------


@pytest.mark.parametrize("code", ALL_35_CODES)
def test_a_row_carrying_each_relationship_type_code_reads_back_through_row_to_relationship(
    seeded_entities: Engine, code: str
) -> None:
    """Writes one raw `entity_relationships` row for `code`, then reads it back
    through `SqlEntityRepository.relationship` -- which calls
    `_row_to_relationship`, the exact call site that used to raise
    `ValueError` for the twenty new codes before the enum was widened, and
    for `design_coordinates_with`/`design_coordination_with` specifically
    until this revision's rename. No exception, and the typed field
    round-trips, for all thirty-five codes -- not only the twenty new ones.
    """
    relationship_id = _relationship_id(ALL_35_CODES.index(code))
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
        # enum admits `code`.
        relationship = repository.relationship(PRINCIPAL, relationship_id)

    assert relationship is not None
    assert relationship.relationship_type == EntityRelationshipType(code)
    assert relationship.relationship_type.value == code
    assert relationship.from_entity_id == FROM_ORG
    assert relationship.to_entity_id == TO_ORG


def test_all_thirty_five_codes_also_read_back_through_the_paged_relationships_list(
    seeded_entities: Engine,
) -> None:
    """`SqlEntityRepository.relationships` (the paged, per-entity list) also
    calls `_row_to_relationship` for every row -- proven once, for all
    thirty-five codes in one page, rather than assuming the single-row
    `relationship` accessor above is the only caller that matters.
    """
    with seeded_entities.begin() as connection:
        for index, code in enumerate(ALL_35_CODES):
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
        ALL_35_CODES
    )


# --- the DB-level taxonomy and the enum are exact two-directional mirrors ----


def test_the_seeded_taxonomy_table_and_the_enum_are_exact_mirrors(
    migrated_engine: Engine,
) -> None:
    """The genuine parity check: not merely matching counts, but matching
    *sets*. No code seeded in `entity_relationship_types` without a matching
    `EntityRelationshipType` member, and no enum member without a matching
    seeded row -- proving `design_coordination_with` (the renamed successor
    to the previously-withheld `design_coordinates_with`) is present on both
    sides, alongside every other code.
    """
    with migrated_engine.connect() as connection:
        seeded_codes = set(
            connection.execute(
                text(f"SELECT relationship_type_code FROM {SCHEMA}.entity_relationship_types")  # noqa: S608
            ).scalars()
        )
    enum_values = {member.value for member in EntityRelationshipType}

    assert len(seeded_codes) == 35
    assert len(enum_values) == 35
    assert seeded_codes == enum_values
    assert seeded_codes - enum_values == set()
    assert enum_values - seeded_codes == set()
    assert "design_coordinates_with" not in seeded_codes
    assert "design_coordination_with" in seeded_codes
    assert EntityRelationshipType.DESIGN_COORDINATION_WITH.value == "design_coordination_with"
