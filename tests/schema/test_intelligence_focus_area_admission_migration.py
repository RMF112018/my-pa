"""`93f3aa113f58`: three focus areas admitted on the Intelligence Artifact plane.

The revision restates the three server-named focus-area CHECKs so they admit
`captures`, `notes` and `field_intelligence` beside the original six. It adds no
table and no row. Downgrade restores the six-value CHECKs and deletes nothing:
a row holding a new value makes it fail with `check_violation`.
"""

from __future__ import annotations

import ast
import io
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError
from tests.conftest import DEFAULT_LIMITS, metadata_for, operator

from my_pa.application.commands import BeginIntelligenceCycle, CommitIntelligenceArtifact
from my_pa.application.service import ApplicationService
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
    SourceLaneId,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

ROOT: Final = Path(__file__).resolve().parents[2]
VERSIONS: Final = ROOT / "migrations" / "versions"
REVISION: Final = "93f3aa113f58"
PREVIOUS: Final = "6734f039f7a6"
MIGRATION: Final = VERSIONS / "20261007_93f3aa113f58_intelligence_focus_area_admission.py"
PLANE_MIGRATION: Final = VERSIONS / "20260820_e9b2c4d7a150_admit_intelligence_artifact_plane.py"
CHECK_VIOLATION: Final = "23514"
WHEN: Final = datetime(2026, 10, 7, 12, tzinfo=UTC)

ORIGINAL: Final[tuple[str, ...]] = (
    "risk_deadline_exception",
    "decision_approval",
    "communications",
    "project_program_pulse",
    "watchlist_dependency",
    "action_commitment",
)
ADMITTED: Final[tuple[str, ...]] = ("captures", "notes", "field_intelligence")

#: (table, focus column, key column substituted on a copied row, CHECK name),
#: with the CHECK names read from `pg_constraint` at `PREVIOUS`, not assumed.
CHECKS: Final = (
    (
        "intelligence_producer_runs",
        "focus_area_id",
        "run_id",
        "intelligence_producer_runs_focus_area_id_check",
    ),
    (
        "intelligence_artifacts",
        "focus_area_id",
        "artifact_id",
        "intelligence_artifacts_focus_area_id_check",
    ),
    (
        "intelligence_pipeline_dependencies",
        "expected_focus_area_id",
        "downstream_artifact_id",
        "intelligence_pipeline_dependencies_expected_focus_area_id_check",
    ),
)
_WHITESPACE: Final = re.compile(r"\s+")
_LITERAL: Final = re.compile(r"'([a-z_]+)'")


def _config(buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


def _constant(name: str) -> tuple[str, ...]:
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, tuple)
            return value
    raise AssertionError(f"{name} is not a module-level constant of {MIGRATION.name}")


# ---- FAST: the graph and the freeze -----------------------------------------------


def test_the_revision_is_the_single_head_directly_on_the_knowledge_revision() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_revision_imports_no_domain_or_persistence_modules() -> None:
    """`D-48`/`D-69`: the vocabulary is frozen text, never derived from `FocusAreaId`."""
    source = MIGRATION.read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported <= {"alembic", "__future__", "typing", "collections.abc"}
    assert "my_pa" not in source
    assert "FocusAreaId" not in source
    code = source.split('"""', 2)[2].upper()
    for statement in ("CREATE TABLE", "DROP TABLE", "DELETE FROM", "UPDATE ", "GRANT "):
        assert statement not in code


def test_the_before_literal_is_exactly_what_the_plane_revision_emitted() -> None:
    plane = _WHITESPACE.sub(" ", PLANE_MIGRATION.read_text(encoding="utf-8"))
    emitted = re.findall(r"focus_area_id IN \(([^)]*)\)", plane)
    assert len(emitted) == 3
    for block in emitted:
        assert tuple(_LITERAL.findall(block)) == ORIGINAL
    assert _constant("_FOCUS_AREAS_BEFORE") == ORIGINAL


def test_the_after_literal_appends_exactly_the_three_admitted_areas() -> None:
    assert _constant("_FOCUS_AREAS_AFTER") == (*ORIGINAL, *ADMITTED)
    assert _constant("_CHECKS") == tuple((table, column, name) for table, column, _, name in CHECKS)


def test_the_offline_upgrade_and_downgrade_restate_each_check_by_name() -> None:
    for target, down, vocabulary in (
        (f"{PREVIOUS}:{REVISION}", False, (*ORIGINAL, *ADMITTED)),
        (f"{REVISION}:{PREVIOUS}", True, ORIGINAL),
    ):
        buffer = io.StringIO()
        action = command.downgrade if down else command.upgrade
        action(_config(buffer), target, sql=True)
        rendered = _WHITESPACE.sub(" ", buffer.getvalue())
        literals = ", ".join(f"'{value}'" for value in vocabulary)
        for table, column, _, name in CHECKS:
            assert f'ALTER TABLE knowledge.{table} DROP CONSTRAINT "{name}"' in rendered
            assert (
                f'ALTER TABLE knowledge.{table} ADD CONSTRAINT "{name}" '
                f"CHECK ({column} IS NULL OR {column} IN ({literals}))"
            ) in rendered


# ---- the database --------------------------------------------------------------------


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    return empty_database_url


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    built = create_database_engine(disposable_database)
    try:
        yield built
    finally:
        built.dispose()


def _version(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _definitions(engine: Engine) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = 'knowledge' AND c.contype = 'c' "
                "AND t.relname LIKE 'intelligence\\_%' "
                "AND pg_get_constraintdef(c.oid) LIKE '%focus_area_id = ANY%'"
            )
        ).all()
    return {str(name): str(definition) for name, definition in rows}


def _admitted_by(definition: str) -> tuple[str, ...]:
    return tuple(_LITERAL.findall(definition))


def _service(engine: Engine) -> ApplicationService:
    audit = SqlAlchemyAuditSink(engine)
    return ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=audit),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
    )


def _ok(service: ApplicationService, principal: Principal, command_: object) -> dict[str, object]:
    envelope = service.invoke(
        metadata_for(command_.capability, Purpose.REPORT_AUTHORING, principal),  # type: ignore[attr-defined]
        command_,  # type: ignore[arg-type]
        principal=principal,
    )
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    return envelope.result


def _commit(
    service: ApplicationService,
    principal: Principal,
    cycle: str,
    *,
    stage: IntelligenceStage,
    kind: ArtifactKind,
    focus: FocusAreaId,
    key: str,
    lane: SourceLaneId | None = None,
    dependencies: tuple[str, ...] = (),
) -> str:
    result = _ok(
        service,
        principal,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=stage,
            artifact_kind=kind,
            producer_task_id=f"mig-{key}",
            producer_task_name=key,
            automation_platform="abacus_chatllm",
            report_date="2026-10-07",
            title=key,
            body_markdown=f"synthetic {key}",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key=key,
            focus_area_id=focus,
            source_lane=lane,
            dependency_report_ids=dependencies,
        ),
    )
    report_id = result["report_id"]
    assert isinstance(report_id, str)
    return report_id


def _seed(engine: Engine, focus: FocusAreaId, key: str) -> None:
    """One collector and one researcher depending on it: a row in each table."""
    service = _service(engine)
    principal = operator()
    cycle = _ok(
        service,
        principal,
        BeginIntelligenceCycle(
            cycle_id=CYCLE_MORNING_INTELLIGENCE,
            business_date="2026-10-07",
            idempotency_key=f"{key}-cycle",
        ),
    )["cycle_run_id"]
    assert isinstance(cycle, str)
    collector = _commit(
        service,
        principal,
        cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        focus=focus,
        key=f"{key}-collector",
    )
    _commit(
        service,
        principal,
        cycle,
        stage=IntelligenceStage.RESEARCHER,
        kind=ArtifactKind.RESEARCH_CONTEXT,
        focus=focus,
        key=f"{key}-teams",
        lane=SourceLaneId.TEAMS,
        dependencies=(collector,),
    )


def _copy_with(
    connection: Connection, table: str, key_column: str, column: str, value: str
) -> None:
    """Insert a copy of one `communications` row with a fresh key and `column` = `value`.

    No intelligence table has a BEFORE INSERT trigger, so the CHECK decides.
    """
    columns = list(
        connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'knowledge' AND table_name = :table "
                "AND is_generated = 'NEVER' ORDER BY ordinal_position"
            ),
            {"table": table},
        ).scalars()
    )
    swapped = {
        "downstream_artifact_id": "upstream_artifact_id",
        "upstream_artifact_id": "downstream_artifact_id",
    }
    chosen = []
    for name in columns:
        if name == column:
            chosen.append(":value")
        elif table == "intelligence_pipeline_dependencies":
            # A reversed edge is a fresh primary key over the same two artifacts.
            chosen.append(swapped.get(name, name))
        elif name == key_column:
            chosen.append(f"{name} || 'Zz9'")
        else:
            chosen.append(name)
    connection.execute(
        text(
            f"INSERT INTO knowledge.{table} ({', '.join(columns)}) "  # noqa: S608
            f"SELECT {', '.join(chosen)} FROM knowledge.{table} "
            f"WHERE {column} = 'communications' LIMIT 1"
        ),
        {"value": value},
    )


def _refused(engine: Engine, table: str, key_column: str, column: str, value: str) -> str | None:
    """The violated CHECK's name, or None when the copy was admitted (rolled back)."""
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            _copy_with(connection, table, key_column, column, value)
        except DBAPIError as error:
            transaction.rollback()
            assert getattr(error.orig, "sqlstate", None) == CHECK_VIOLATION
            return str(error.orig.diag.constraint_name)  # type: ignore[union-attr]
        transaction.rollback()
        return None


@pytest.mark.database
@pytest.mark.migration_edge
def test_the_knowledge_revision_upgrades_to_admit_the_three_areas(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), PREVIOUS)
    before = _definitions(engine)
    assert set(before) == {name for *_, name in CHECKS}
    assert all(_admitted_by(definition) == ORIGINAL for definition in before.values())
    _seed(engine, FocusAreaId.COMMUNICATIONS, "mig-before")
    for table, column, key_column, name in CHECKS:
        for value in ADMITTED:
            assert _refused(engine, table, key_column, column, value) == name

    command.upgrade(_config(), REVISION)
    assert _version(engine) == REVISION
    after = _definitions(engine)
    assert set(after) == set(before)
    assert all(_admitted_by(definition) == (*ORIGINAL, *ADMITTED) for definition in after.values())
    for table, column, key_column, name in CHECKS:
        for value in ADMITTED:
            assert _refused(engine, table, key_column, column, value) is None
        assert _refused(engine, table, key_column, column, "bogus") == name


@pytest.mark.database
def test_downgrade_refuses_while_a_row_holds_an_admitted_area(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), "head")
    _seed(engine, FocusAreaId.CAPTURES, "mig-captures")
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert getattr(refused.value.orig, "sqlstate", None) == CHECK_VIOLATION
    assert _version(engine) == REVISION
    assert all(
        _admitted_by(definition) == (*ORIGINAL, *ADMITTED)
        for definition in _definitions(engine).values()
    )
    with engine.connect() as connection:
        kept = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.intelligence_artifacts "
                "WHERE focus_area_id = 'captures'"
            )
        ).scalar_one()
    assert kept == 2


@pytest.mark.database
def test_a_downgrade_without_admitted_rows_restores_the_six_value_checks(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), PREVIOUS)
    before = _definitions(engine)
    command.upgrade(_config(), "head")
    _seed(engine, FocusAreaId.COMMUNICATIONS, "mig-round")
    command.downgrade(_config(), PREVIOUS)
    assert _version(engine) == PREVIOUS
    assert _definitions(engine) == before
    for table, column, key_column, name in CHECKS:
        assert _refused(engine, table, key_column, column, "captures") == name
    command.upgrade(_config(), "head")
    assert _version(engine) == REVISION
