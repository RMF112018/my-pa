"""CCA-005 / WP-TUX-01 legacy direct-Principal Task origin reconciliation.

Revision `6f6ead27d122` revises `e6a4c2f91b73`. It is a data-only correction
of WP-TUX-01's backfill: rows that already carried
`acceptance_kind = 'direct_principal'` were backfilled to
`origin_kind = 'evidence'` with `origin_evidence_ref` unchanged, which the
domain `Task` and the `a_task_origin_matches_its_provenance` CHECK both
refuse. The revision repairs exactly that class in one UPDATE, changing both
columns together so the CHECK is satisfied at every instant.

This module asserts the chain position, the correction itself, the surviving
CHECKs, domain reconstruction, pulse derivation, the `context.prepare`
Continuity path, empty-to-head, and the documented no-op downgrade. The
fixture/engine/`Config`/`command.upgrade` idiom is copied from
`tests/schema/test_wp_tux_01_task_origin_closure_comments_migration.py`.
Every identifier literal is frozen (`prn_`/`tsk_`/`cap_`/`corr_` style,
8-64 alphanumerics) and every vocabulary literal is restated, not imported
from a domain enum (`D-69`).
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, NoReturn

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from my_pa.application.authorization import Authorization
from my_pa.application.context.providers import ContextPlane, _search_continuity
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import POLICY_VERSION, PolicyDecision
from my_pa.domain.search.query import SearchQuery
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.situation_repository import (
    SqlContinuityRepository,
    SqlPulseRepository,
)

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "6f6ead27d122"
PREVIOUS: Final = "e6a4c2f91b73"

PRINCIPAL: Final = "prn_aaaaaaaa11111111"
TASK_LEGACY: Final = "tsk_aaaaaaaa11111111"
TASK_EVIDENCE: Final = "tsk_bbbbbbbb22222222"
TASK_ALREADY_DIRECT: Final = "tsk_cccccccc33333333"
ORIGIN_LEGACY: Final = "corr_aaaaaaaa11111111"
ORIGIN_EVIDENCE: Final = "cap_aaaaaaaa11111111"
WHEN: Final = datetime(2026, 9, 22, 12, tzinfo=UTC)
DUE: Final = WHEN + timedelta(days=1)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; this module drives Alembic itself."""
    return empty_database_url


def _seed_task(
    connection: Connection,
    *,
    task_id: str,
    origin_kind: str,
    origin_evidence_ref: str | None,
    acceptance_kind: str,
    evidence_state: str,
    due_at: datetime | None = None,
) -> None:
    """One `knowledge.tasks` row at the head shape, every NOT NULL column set.

    The column set matches the insert shape the WP-TUX-01 provenance test uses:
    `origin_kind`, `acceptance_kind`, `lifecycle_state`, `version`, `opened_at`,
    `created_at`, `updated_at`, `title`, `state`, `evidence_state`,
    `principal_id`, `task_id`.
    """
    connection.execute(
        text(
            """
            INSERT INTO knowledge.tasks (
              task_id, principal_id, title, state, evidence_state,
              origin_kind, origin_evidence_ref, opened_at, due_at,
              acceptance_kind, created_at, updated_at, lifecycle_state, version
            ) VALUES (
              :task_id, :principal_id, 'Seeded task', 'open', :evidence_state,
              :origin_kind, :origin_evidence_ref, :when, :due_at,
              :acceptance_kind, :when, :when, 'open', 1
            )
            """
        ),
        {
            "task_id": task_id,
            "principal_id": PRINCIPAL,
            "evidence_state": evidence_state,
            "origin_kind": origin_kind,
            "origin_evidence_ref": origin_evidence_ref,
            "when": WHEN,
            "due_at": due_at,
            "acceptance_kind": acceptance_kind,
        },
    )


def _seed_the_three_tasks(connection: Connection) -> None:
    """The three rows the correction is about, at the predecessor head.

    `TASK_LEGACY` is the defect: `acceptance_kind = 'direct_principal'` with
    `origin_kind = 'evidence'` and a non-null reference, which WP-TUX-01's
    backfill produced and the domain refuses. `TASK_EVIDENCE` is a legitimate
    evidence-origin row that must survive untouched. `TASK_ALREADY_DIRECT` is a
    legitimate post-WP-TUX-01 direct-Principal row that must survive untouched.
    """
    _seed_task(
        connection,
        task_id=TASK_LEGACY,
        origin_kind="evidence",
        origin_evidence_ref=ORIGIN_LEGACY,
        acceptance_kind="direct_principal",
        evidence_state="accepted",
        due_at=DUE,
    )
    _seed_task(
        connection,
        task_id=TASK_EVIDENCE,
        origin_kind="evidence",
        origin_evidence_ref=ORIGIN_EVIDENCE,
        acceptance_kind="none",
        evidence_state="proposed",
    )
    _seed_task(
        connection,
        task_id=TASK_ALREADY_DIRECT,
        origin_kind="direct_principal",
        origin_evidence_ref=None,
        acceptance_kind="direct_principal",
        evidence_state="accepted",
    )


def _origin_rows(engine: Engine) -> dict[str, tuple[str, str | None]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT task_id, origin_kind, origin_evidence_ref "
                "FROM knowledge.tasks ORDER BY task_id"
            )
        ).mappings()
        return {row["task_id"]: (row["origin_kind"], row["origin_evidence_ref"]) for row in rows}


# --- a. chain position (no database) -----------------------------------------


def test_the_revision_is_in_the_chain() -> None:
    """Sole head is `7a5c4e9d2b61`, additive on this revision."""
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert script.get_heads() == ["7a5c4e9d2b61"]
    assert script.get_revision("7a5c4e9d2b61").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS


# --- b. predecessor-to-head: the correction ----------------------------------


@pytest.mark.database
def test_predecessor_to_head_reconciles_legacy_direct_principal_origins(
    disposable_database: str,
) -> None:
    """Only the misclassified class changes; both columns change together."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS)
        with engine.begin() as connection:
            _seed_the_three_tasks(connection)
        command.upgrade(_config(), REVISION)
        rows = _origin_rows(engine)
        assert rows[TASK_LEGACY] == ("direct_principal", None)
        assert rows[TASK_EVIDENCE] == ("evidence", ORIGIN_EVIDENCE)
        assert rows[TASK_ALREADY_DIRECT] == ("direct_principal", None)
    finally:
        engine.dispose()


# --- c. the surviving provenance CHECK ---------------------------------------


@pytest.mark.database
def test_the_reconciled_rows_satisfy_the_provenance_check(
    disposable_database: str,
) -> None:
    """The CHECK still refuses both invalid pairings after the correction."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        # evidence origin with a NULL reference is still refused.
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.tasks (
                      task_id, principal_id, title, state, evidence_state,
                      origin_kind, origin_evidence_ref, opened_at,
                      acceptance_kind, created_at, updated_at,
                      lifecycle_state, version
                    ) VALUES (
                      'tsk_dddddddd44444444', :principal_id, 'Broken evidence',
                      'open', 'proposed', 'evidence', NULL, :when,
                      'none', :when, :when, 'open', 1
                    )
                    """
                ),
                {"principal_id": PRINCIPAL, "when": WHEN},
            )
        # direct_principal origin with a non-null reference is still refused.
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.tasks (
                      task_id, principal_id, title, state, evidence_state,
                      origin_kind, origin_evidence_ref, opened_at,
                      acceptance_kind, created_at, updated_at,
                      lifecycle_state, version
                    ) VALUES (
                      'tsk_eeeeeeee55555555', :principal_id, 'Broken direct',
                      'open', 'accepted', 'direct_principal', :origin, :when,
                      'direct_principal', :when, :when, 'open', 1
                    )
                    """
                ),
                {"principal_id": PRINCIPAL, "when": WHEN, "origin": ORIGIN_LEGACY},
            )
    finally:
        engine.dispose()


# --- d. domain reconstruction -------------------------------------------------


@pytest.mark.database
def test_the_reconciled_row_reconstructs_the_domain_task(
    disposable_database: str,
) -> None:
    """`SqlContinuityRepository._to_task` no longer raises on the legacy row.

    Before the correction the row paired `acceptance_kind = 'direct_principal'`
    with a non-null `origin_evidence_ref`, which the domain `Task` refuses; the
    corrected row reconstructs cleanly.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS)
        with engine.begin() as connection:
            _seed_the_three_tasks(connection)
        command.upgrade(_config(), REVISION)
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT * FROM knowledge.tasks WHERE task_id = :task_id"),
                {"task_id": TASK_LEGACY},
            ).one()
        task = SqlContinuityRepository._to_task(row)
        assert task.task_id == TASK_LEGACY
        assert task.origin_evidence_ref is None
    finally:
        engine.dispose()


# --- e. pulse derivation ------------------------------------------------------


@pytest.mark.database
def test_derive_pulse_succeeds_with_the_corrected_task(
    disposable_database: str,
) -> None:
    """`SqlPulseRepository.derive_pulse` emits the corrected accepted task.

    The task is accepted, open, and due within the 72-hour window, so the
    derived pulse includes it — and, critically, the derivation no longer
    raises while reconstructing the row.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS)
        with engine.begin() as connection:
            _seed_the_three_tasks(connection)
        command.upgrade(_config(), REVISION)
        with engine.connect() as connection:
            pulse = SqlPulseRepository(connection).derive_pulse(PRINCIPAL, WHEN)
        assert any(item.item_ref == TASK_LEGACY for item in pulse)
    finally:
        engine.dispose()


# --- f. context.prepare Continuity path ---------------------------------------


class _EmptyContinuity:
    """A situations/projects repository that holds nothing."""

    def list_situations(self, principal_id: str) -> tuple[Any, ...]:
        return ()

    def list_projects(self, principal_id: str) -> tuple[Any, ...]:
        return ()


class _ThinUnitOfWork:
    """The smallest UnitOfWork `_search_continuity` can run against.

    Only the members the Continuity gather reads are provided: the situations
    and projects listings (empty), `pulse`, whose `derive_pulse` is the real
    `SqlPulseRepository` on the same connection — so a ValueError inside the
    derivation would propagate out of `_search_continuity` exactly as it would
    in production — and `continuity_read`, which refuses with
    `NotImplementedError` exactly as the `UnitOfWork` port's default does, so
    the optional read-model extension is skipped rather than faulted.
    """

    def __init__(self, connection: Connection) -> None:
        self.pulse = SqlPulseRepository(connection)

    @property
    def situations(self) -> _EmptyContinuity:
        return _EmptyContinuity()

    @property
    def projects(self) -> _EmptyContinuity:
        return _EmptyContinuity()

    @property
    def continuity_read(self) -> NoReturn:
        raise NotImplementedError


@pytest.mark.database
def test_context_prepare_continuity_path_does_not_raise(
    disposable_database: str,
) -> None:
    """`_search_continuity` runs the corrected task through `derive_pulse`.

    The query is chosen not to match the pulse item, so the gather completes
    with no evidence; the assertion is that the derivation inside it does not
    raise. No broad exception handling is added to production code; the fix is
    the data correction itself.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS)
        with engine.begin() as connection:
            _seed_the_three_tasks(connection)
        command.upgrade(_config(), REVISION)
        authorization = Authorization(
            principal=Principal(
                principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
            capability=Capability.CONTEXT_PREPARE,
            purpose=Purpose.CONTEXT_PREPARATION,
            correlation_id="corr_aaaaaaaa11111111",
            request_id="req_aaaaaaaa11111111",
            audit_id="aud_aaaaaaaa11111111",
            at=WHEN,
            decision=PolicyDecision(allowed=True, policy_version=POLICY_VERSION),
            requested_source_ids=frozenset(),
            enrollments=(),
        )
        with engine.connect() as connection:
            gather = _search_continuity(
                _ThinUnitOfWork(connection),
                authorization,
                SearchQuery("current work priorities"),
                (),
                (),
            )
        assert gather.plane is ContextPlane.CONTINUITY
        assert not gather.internal_fault
    finally:
        engine.dispose()


# --- g. empty-to-head ---------------------------------------------------------


@pytest.mark.database
def test_empty_to_head_still_works(disposable_database: str) -> None:
    """Data-only: empty-to-head installs no new tables and downgrades cleanly."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.connect() as connection:
            tables = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                    ),
                    {"schema": SCHEMA},
                ).scalars()
            )
        assert "tasks" in tables
        command.downgrade(_config(), "base")
        with engine.connect() as connection:
            remaining = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                    ),
                    {"schema": SCHEMA},
                ).scalars()
            )
        assert remaining == set()
    finally:
        engine.dispose()


# --- h. downgrade is a documented no-op on data -------------------------------


@pytest.mark.database
def test_downgrade_from_head_is_a_no_op_on_data(disposable_database: str) -> None:
    """Downgrade to the predecessor leaves the corrected row corrected.

    Reversing would require the discarded `origin_evidence_ref` values, which
    the revision does not retain; the documented no-op is asserted by checking
    the row is unchanged after the downgrade.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS)
        with engine.begin() as connection:
            _seed_the_three_tasks(connection)
        command.upgrade(_config(), REVISION)
        command.downgrade(_config(), PREVIOUS)
        rows = _origin_rows(engine)
        assert rows[TASK_LEGACY] == ("direct_principal", None)
        assert rows[TASK_EVIDENCE] == ("evidence", ORIGIN_EVIDENCE)
        assert rows[TASK_ALREADY_DIRECT] == ("direct_principal", None)
    finally:
        engine.dispose()
