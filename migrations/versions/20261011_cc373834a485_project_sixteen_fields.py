"""Admit 16 Continuity Project fields: aliases, number, taxonomy, address, value, dates.

Revision ID: cc373834a485
Revises: 93f3aa113f58
Create Date: 2026-10-11

Sixteen new columns on `knowledge.projects`: `aliases` (a replacement-set
JSONB array, the same shape `participants` already has), `project_number`
(unique per Principal, immutable once set), `sector`/`type` (the 9/42-member
`Construction_Project_Taxonomy_v1.csv` vocabulary — the 1-sector-per-type
pairing itself is enforced in `domain.situation.situation.TYPE_TO_SECTOR`,
not restated here as a duplicated 42-branch CHECK), `address`/`city`/
`county`/`address_state`/`zip` (independent free-text fields; `address_state`
rather than `state` because `projects.state` already names the lifecycle
column), `value` (USD, `numeric(14,2)`, never negative), and six independent
schedule dates with no cross-field ordering constraint.

Literals are frozen here rather than derived from the domain enums (`D-48` /
architecture freeze, the same convention `9f2c8a1d4e70` and `2774329487be`
already follow). Downgrade refuses when any row carries a non-default value
in any of the 16 columns, so populated data cannot be dropped silently.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "cc373834a485"
down_revision: str | None = "93f3aa113f58"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: `ProjectSector`'s 9 members, frozen (`D-48`) rather than derived.
_SECTORS_SQL: Final = (
    "'education_civic_and_community', 'healthcare_and_life_sciences', "
    "'hospitality_and_commercial', 'housing_and_residential', "
    "'industrial_logistics_and_technology', 'land_resource_and_specialty', "
    "'recreation_and_entertainment', 'transportation_and_mobility', "
    "'utilities_energy_and_environmental'"
)

#: `ProjectType`'s 42 members, frozen (`D-48`) rather than derived.
_TYPES_SQL: Final = (
    "'acute_care_and_hospitals', 'agricultural_horticultural_and_aquaculture_facilities', "
    "'automotive_and_consumer_mobility_services', 'aviation_and_spaceport_infrastructure', "
    "'culture_performing_arts_and_religious_facilities', 'data_centers_and_telecommunications', "
    "'defense_and_military_facilities', 'early_childhood_and_k_12_schools', "
    "'entertainment_gaming_and_attractions', "
    "'environmental_remediation_and_ecosystem_restoration', "
    "'extractive_and_mineral_resources_facilities', 'government_and_civic_buildings', "
    "'higher_education_and_academic_facilities', 'hotels_resorts_and_lodging', "
    "'industrial_manufacturing_and_processing', 'land_development_enabling_and_civil_sitework', "
    "'life_sciences_and_laboratory_facilities', 'marine_port_and_coastal_transportation', "
    "'mixed_use_buildings_and_districts', 'multifamily_housing', 'office_and_workplace', "
    "'outpatient_and_specialty_healthcare', 'parking_and_fleet_infrastructure', "
    "'parks_landscape_and_public_realm', 'power_fuel_and_utility_networks', "
    "'power_generation_and_energy_storage', 'public_safety_courts_and_corrections', "
    "'rail_bus_and_public_transit', 'restaurants_and_foodservice', "
    "'retail_shopping_and_consumer_services', 'roads_bridges_and_tunnels', "
    "'senior_living_and_residential_care', 'single_family_housing', "
    "'social_services_and_community_facilities', "
    "'specialty_construction_scopes_and_building_renewal', "
    "'sports_recreation_and_wellness_facilities', "
    "'stormwater_flood_control_and_coastal_protection', "
    "'student_staff_and_group_housing', 'transitional_supportive_and_emergency_housing', "
    "'warehousing_logistics_and_cold_chain', 'wastewater_and_solid_waste', "
    "'water_supply_and_treatment'"
)

#: The 16 new columns, in `upgrade()`/`downgrade()` order.
_NEW_COLUMNS: Final[tuple[str, ...]] = (
    "aliases",
    "project_number",
    "sector",
    "type",
    "address",
    "city",
    "county",
    "address_state",
    "zip",
    "value",
    "scheduled_start",
    "contract_start",
    "actual_start",
    "scheduled_finish",
    "contract_finish",
    "actual_finish",
)

#: Every new CHECK constraint this revision adds, for `downgrade()` to drop.
_NEW_CHECK_CONSTRAINTS: Final[tuple[str, ...]] = (
    "a_project_number_is_not_blank",
    "a_project_sector_is_known",
    "a_project_type_is_known",
    "a_project_sector_and_type_are_both_set_or_neither",
    "a_project_value_is_non_negative",
)


def _refuse(*, name: str, offending_sql: str, message: str) -> None:
    """Fail closed when `offending_sql` yields any row.

    Emitting the guard as server SQL keeps offline `--sql` mode honest and
    keeps the refusal message free of row payloads beyond a count. Mirrors
    `9f2c8a1d4e70`'s `_refuse` exactly.
    """
    escaped_name = name.replace("'", "''")
    escaped_message = message.replace("'", "''")
    op.execute(
        f"""
        DO $$
        DECLARE
          offending_count integer;
        BEGIN
          WITH offending AS (
            {offending_sql}
          )
          SELECT count(*) INTO offending_count FROM offending;
          IF offending_count > 0 THEN
            RAISE EXCEPTION
              'cc373834a485 refused ({escaped_name}): % row(s). {escaped_message}',
              offending_count;
          END IF;
        END $$
        """  # noqa: S608
    )


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE {SCHEMA}.projects "
        "ADD COLUMN aliases jsonb NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN project_number text")
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN sector text")
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN type text")
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN address text")
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN city text")
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN county text")
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN address_state text")
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN zip text")
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN value numeric(14, 2)")
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN scheduled_start date")
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN contract_start date")
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN actual_start date")
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN scheduled_finish date")
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN contract_finish date")
    op.execute(f"ALTER TABLE {SCHEMA}.projects ADD COLUMN actual_finish date")

    op.execute(
        f"ALTER TABLE {SCHEMA}.projects ADD CONSTRAINT a_project_number_is_not_blank "
        "CHECK (project_number IS NULL OR length(trim(project_number)) > 0 "
        "AND length(project_number) <= 64)"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.projects ADD CONSTRAINT a_project_sector_is_known "
        f"CHECK (sector IS NULL OR sector IN ({_SECTORS_SQL}))"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.projects ADD CONSTRAINT a_project_type_is_known "
        f"CHECK (type IS NULL OR type IN ({_TYPES_SQL}))"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.projects "
        "ADD CONSTRAINT a_project_sector_and_type_are_both_set_or_neither "
        "CHECK ((sector IS NULL) = (type IS NULL))"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.projects ADD CONSTRAINT a_project_value_is_non_negative "
        "CHECK (value IS NULL OR value >= 0)"
    )

    op.execute(
        f"CREATE UNIQUE INDEX a_project_number_is_unique_per_principal "
        f"ON {SCHEMA}.projects (principal_id, project_number) "
        "WHERE project_number IS NOT NULL"
    )

    # Defense-in-depth backstop for the application-layer immutability check
    # in `domain.situation.project_history.execute_update_project`'s `change()`
    # closure: even a future direct-SQL fix-up or an application bug cannot
    # silently change a `project_number` once set.
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.project_number_is_immutable_once_set() RETURNS trigger
          LANGUAGE plpgsql AS $$
          BEGIN
            IF OLD.project_number IS NOT NULL
               AND NEW.project_number IS DISTINCT FROM OLD.project_number THEN
              RAISE EXCEPTION 'project_number is immutable once set'
                USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
          END;
          $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER a_project_number_does_not_change BEFORE UPDATE ON
            {SCHEMA}.projects FOR EACH ROW EXECUTE FUNCTION
            {SCHEMA}.project_number_is_immutable_once_set()
        """
    )


def downgrade() -> None:
    # `aliases` is `NOT NULL DEFAULT '[]'::jsonb`, never literally NULL, so its
    # "populated" test is against the empty-array default rather than NULL —
    # every other column is genuinely nullable and untouched means NULL.
    nullable_columns = [column for column in _NEW_COLUMNS if column != "aliases"]
    populated_sql = " OR ".join(
        [f"{column} IS NOT NULL" for column in nullable_columns]
        + ["aliases <> '[]'::jsonb"]
    )
    _refuse(
        name="populated new Project fields",
        offending_sql=(
            f"SELECT project_id FROM {SCHEMA}.projects WHERE {populated_sql}"  # noqa: S608
        ),
        message=(
            "Dropping these columns would destroy real Project data; clear the "
            "16 new fields on every Project before downgrade."
        ),
    )
    op.execute(f"DROP TRIGGER IF EXISTS a_project_number_does_not_change ON {SCHEMA}.projects")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.project_number_is_immutable_once_set()")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.a_project_number_is_unique_per_principal")
    for constraint in _NEW_CHECK_CONSTRAINTS:
        op.execute(f"ALTER TABLE {SCHEMA}.projects DROP CONSTRAINT IF EXISTS {constraint}")
    for column in _NEW_COLUMNS:
        op.execute(f"ALTER TABLE {SCHEMA}.projects DROP COLUMN IF EXISTS {column}")
