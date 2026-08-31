"""Revision `9a3f6c1e8d24`: widen the identity-correction family vocabulary.

RI-ENT-WP-06b. Three `CHECK (record_family IN (...))` constraints --
`entity_identity_effects.an_identity_effect_family_is_known`,
`entity_identity_preview_ambiguities.a_preview_ambiguity_family_is_known`,
`entity_identity_ambiguity_settlements.an_ambiguity_settlement_family_is_known`
-- are widened from twelve values to eighteen, admitting the six new
`IdentityEffectFamily` members RI-ENT-WP-06b's merge/split wiring writes:
`name`, `organization_profile`, `address`, `communication_method`,
`project_participation`, `person_organization_affiliation`.

Two claims: upgraded to head, all three constraints admit all eighteen
values (read directly out of `pg_catalog` via `pg_get_constraintdef`, on
`test_capture_client_migration.py`'s own precedent for asserting a `CHECK`
behaviourally rather than trusting its name); downgraded to the revision
below, all three constraints admit only the original twelve -- the six new
values are gone, not merely additional ones present.

The database is disposable, created and dropped by this module's own
fixture under a name no other module uses, and is never the configured one.
"""

from __future__ import annotations

import re
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
DISPOSABLE_DATABASE: Final = "my_pa_widen_identity_family_vocabulary_test"

REVISION: Final = "9a3f6c1e8d24"
PREVIOUS_REVISION: Final = "8dc3619891bb"

_PRIOR_TWELVE: Final = frozenset(
    {
        "entity",
        "alias",
        "identifier",
        "assignment",
        "relationship",
        "observation",
        "proposal",
        "review_case",
        "relationship_memory",
        "memory_proposal",
        "memory_context_link",
        "derived_context",
    }
)

_SIX_NEW: Final = frozenset(
    {
        "name",
        "organization_profile",
        "address",
        "communication_method",
        "project_participation",
        "person_organization_affiliation",
    }
)

_CONSTRAINTS: Final = (
    ("entity_identity_effects", "an_identity_effect_family_is_known"),
    ("entity_identity_preview_ambiguities", "a_preview_ambiguity_family_is_known"),
    ("entity_identity_ambiguity_settlements", "an_ambiguity_settlement_family_is_known"),
)

_CONSTRAINT_DEF: Final = text(
    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
    "JOIN pg_class t ON t.oid = c.conrelid "
    "JOIN pg_namespace n ON n.oid = t.relnamespace "
    "WHERE n.nspname = :schema AND t.relname = :table AND c.conname = :name"
)


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
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _admitted(engine: Engine, table: str, constraint: str) -> frozenset[str]:
    """The values one closed-set constraint admits, read out of the server."""
    with engine.connect() as connection:
        definition = connection.execute(
            _CONSTRAINT_DEF, {"schema": SCHEMA, "table": table, "name": constraint}
        ).scalar_one()
    return frozenset(re.findall(r"'([^']+)'::text", str(definition)))


@pytest.mark.database
def test_upgraded_to_head_all_three_constraints_admit_all_eighteen_values(
    migrated_engine: Engine,
) -> None:
    for table, constraint in _CONSTRAINTS:
        admitted = _admitted(migrated_engine, table, constraint)
        assert admitted == _PRIOR_TWELVE | _SIX_NEW, (table, constraint)


@pytest.mark.database
def test_downgraded_all_three_constraints_admit_only_the_original_twelve(
    migrated_engine: Engine,
) -> None:
    command.downgrade(_config(), PREVIOUS_REVISION)
    for table, constraint in _CONSTRAINTS:
        admitted = _admitted(migrated_engine, table, constraint)
        assert admitted == _PRIOR_TWELVE, (table, constraint)
        assert admitted.isdisjoint(_SIX_NEW), (table, constraint)
    # And upgrading again restores the widened vocabulary -- the pair is a
    # round trip, not a one-way correction.
    command.upgrade(_config(), REVISION)
    for table, constraint in _CONSTRAINTS:
        admitted = _admitted(migrated_engine, table, constraint)
        assert admitted == _PRIOR_TWELVE | _SIX_NEW, (table, constraint)
