"""`c3f8a1d07e94` is what lets an `entities.graph` request be audited at all.

`authorize` commits an `audit_events` row before the handler runs. A capability
in the enum and absent from `capability_is_known` answers `internal_error`
against a migrated database while every from-scratch test passes. This module
inserts `entities.graph` at head, downgrades one revision, and requires the
same insert to be refused.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from my_pa.domain.identity.operation import Capability
from my_pa.infrastructure.database.engine import create_database_engine

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
DISPOSABLE_DATABASE: Final = "my_pa_entities_graph_vocabulary_test"

REVISION: Final = "c3f8a1d07e94"
PREVIOUS_REVISION: Final = "b8e4d1a6c073"
HEAD_REVISION: Final = "6a2f9d1c4b80"
ADMITTED_CAPABILITY: Final = "entities.graph"
SETTLED_CAPABILITY: Final = "capabilities.get"
SETTLED_PURPOSE: Final = "status_observation"
UNDECLARED_CAPABILITY: Final = "nope.nope"
PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
WHEN: Final = datetime(2026, 9, 4, 12, tzinfo=UTC)
POLICY_VERSION: Final = "policy-v1"
_ROWS = count(1)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    return empty_database_url


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _index() -> str:
    return f"{next(_ROWS):016x}"


def _audit(engine: Engine, *, capability: str, purpose: str) -> None:
    index = _index()
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.audit_events "  # noqa: S608
                "(audit_id, correlation_id, principal_id, capability, purpose, outcome, "
                " policy_version, scope_source_id_count, recorded_at) "
                "VALUES (:audit_id, :correlation_id, :principal_id, :capability, :purpose, "
                " 'allowed', :policy_version, 0, :recorded_at)"
            ),
            {
                "audit_id": f"audit_{index}",
                "correlation_id": f"corr_{index}",
                "principal_id": PRINCIPAL,
                "capability": capability,
                "purpose": purpose,
                "policy_version": POLICY_VERSION,
                "recorded_at": WHEN,
            },
        )


def test_the_admitted_name_is_declared() -> None:
    assert Capability.ENTITIES_GRAPH.value == ADMITTED_CAPABILITY
    assert SETTLED_CAPABILITY in {member.value for member in Capability}
    assert UNDECLARED_CAPABILITY not in {member.value for member in Capability}


def test_the_chain_reaches_this_head_and_holds_one(migrated_engine: Engine) -> None:
    script = ScriptDirectory.from_config(_config())
    heads = list(script.get_heads())
    assert heads == [HEAD_REVISION], f"expected exactly {HEAD_REVISION}, found {heads}"
    assert script.get_revision(REVISION).down_revision == PREVIOUS_REVISION
    assert script.get_revision(HEAD_REVISION).down_revision == REVISION
    with migrated_engine.begin() as connection:
        stamped = list(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
    assert stamped == [HEAD_REVISION]


def test_head_admits_entities_graph(migrated_engine: Engine) -> None:
    _audit(migrated_engine, capability=ADMITTED_CAPABILITY, purpose=SETTLED_PURPOSE)


def test_a_name_nothing_declares_is_still_refused(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError) as refusal:
        _audit(migrated_engine, capability=UNDECLARED_CAPABILITY, purpose=SETTLED_PURPOSE)
    assert "capability_is_known" in str(refusal.value)


def test_this_revision_is_what_admits_it(migrated_engine: Engine) -> None:
    command.downgrade(_config(), PREVIOUS_REVISION)
    _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=SETTLED_PURPOSE)
    with pytest.raises(IntegrityError) as refusal:
        _audit(migrated_engine, capability=ADMITTED_CAPABILITY, purpose=SETTLED_PURPOSE)
    assert "capability_is_known" in str(refusal.value)
    command.upgrade(_config(), "head")
    _audit(migrated_engine, capability=ADMITTED_CAPABILITY, purpose=SETTLED_PURPOSE)
