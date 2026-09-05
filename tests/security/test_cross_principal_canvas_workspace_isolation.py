"""Two synthetic Principals; zero canvas-overlay leakage (UI-IMP-WP17).

Database tier, over a disposable database this module creates and drops. The
subject is Principal isolation of the product-owned canvas workspace: Principal
A cannot read or write Principal B's overlay even with the same seed ids.

Every identity is synthetic; no live personal data is used.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final

import pytest
from sqlalchemy import Engine, text

from my_pa.contracts.ports import CanvasWorkspaceRecord
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.canvas_workspace import (
    get_canvas_workspace,
    insert_canvas_workspace,
    update_canvas_workspace,
)

PRINCIPAL_A: Final = "prn_aaaa0001aaaaaaaaaaaaaaaa00000001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbbbbbbbbbbbbbb00000002"
FOCUS: Final = "ent_canvas0001canvas0001canvas00"
WHEN: Final = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

pytestmark = pytest.mark.database


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE knowledge.canvas_workspaces"))
        yield engine
    finally:
        engine.dispose()


def _record(principal_id: str, *, x: float) -> CanvasWorkspaceRecord:
    return CanvasWorkspaceRecord(
        principal_id=principal_id,
        focus_entity_id=FOCUS,
        scope_entity_id=None,
        version=1,
        positions=MappingProxyType({FOCUS: MappingProxyType({"x": x, "y": 0.0})}),
        created_at=WHEN,
        updated_at=WHEN,
    )


def test_principal_a_cannot_read_principal_b_workspace(engine: Engine) -> None:
    with engine.begin() as connection:
        insert_canvas_workspace(connection, _record(PRINCIPAL_A, x=1.0))
        assert get_canvas_workspace(connection, PRINCIPAL_B, FOCUS, None) is None
        owned = get_canvas_workspace(connection, PRINCIPAL_A, FOCUS, None)
    assert owned is not None
    assert owned.principal_id == PRINCIPAL_A
    assert owned.positions[FOCUS]["x"] == 1.0


def test_principal_a_cannot_write_principal_b_workspace(engine: Engine) -> None:
    with engine.begin() as connection:
        insert_canvas_workspace(connection, _record(PRINCIPAL_A, x=1.0))
        insert_canvas_workspace(connection, _record(PRINCIPAL_B, x=2.0))
        update_canvas_workspace(
            connection,
            CanvasWorkspaceRecord(
                principal_id=PRINCIPAL_A,
                focus_entity_id=FOCUS,
                scope_entity_id=None,
                version=2,
                positions={FOCUS: {"x": 9.0, "y": 9.0}},
                created_at=WHEN,
                updated_at=WHEN,
            ),
            expected_version=1,
        )
        remaining = get_canvas_workspace(connection, PRINCIPAL_B, FOCUS, None)
    assert remaining is not None
    assert remaining.version == 1
    assert remaining.positions[FOCUS]["x"] == 2.0
