"""`a591b81f10a2`: the per-Principal Intelligence report type registry.

The revision creates `knowledge.intelligence_report_types`, seeds the five
built-in rows for every Principal already on the Intelligence Artifact plane,
relaxes the artifact-kind CHECKs of producer runs and artifacts to a kind token
(built-in kinds stay bound to their stage), adds `artifact_kind` to the
current-head unique index (heads and lineage are per kind), and restates
`capability_is_known` 201 -> 203 for `reports.types.create` and
`reports.types.list`.

Downgrade deletes nothing. It refuses with `restrict_violation` while a client
type, a non-built-in run or artifact kind, or an audit row naming a new
capability exists; otherwise it restores the original CHECKs and the original
current-head index exactly and drops the table.
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
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateIndex
from tests.conftest import DEFAULT_LIMITS, metadata_for, operator

from my_pa.application.commands import BeginIntelligenceCycle, CommitIntelligenceArtifact
from my_pa.application.service import ApplicationService
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    ARTIFACT_KIND_TOKEN,
    BUILTIN_REPORT_TYPES,
    CYCLE_MORNING_INTELLIGENCE,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
)
from my_pa.domain.intelligence.models import builtin_report_type_definitions
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.tables import (
    intelligence_artifacts,
    intelligence_report_types,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

ROOT: Final = Path(__file__).resolve().parents[2]
VERSIONS: Final = ROOT / "migrations" / "versions"
REVISION: Final = "a591b81f10a2"
#: The chain head: `5c1e7a9b3d42` (Commitment counterparty Entity cutover) is
#: additive on this revision and touches neither the Intelligence plane nor
#: `audit_events`.
HEAD: Final = "5c1e7a9b3d42"
PREVIOUS: Final = "cc373834a485"
MIGRATION: Final = VERSIONS / "20261011_a591b81f10a2_intelligence_report_type_registry.py"
PLANE_MIGRATION: Final = VERSIONS / "20260820_e9b2c4d7a150_admit_intelligence_artifact_plane.py"
VOCABULARY_MIGRATION: Final = VERSIONS / "20261004_6734f039f7a6_knowledge_assertion_layer.py"
TABLE: Final = "intelligence_report_types"
CHECK_VIOLATION: Final = "23514"
RESTRICT_VIOLATION: Final = "23001"
RAISE_EXCEPTION: Final = "P0001"
UNIQUE_VIOLATION: Final = "23505"
HEAD_INDEX: Final = "intelligence_artifact_current_head"
#: `pg_get_indexdef` of the head index before this revision and at it.
HEAD_INDEX_BEFORE: Final = (
    "CREATE UNIQUE INDEX intelligence_artifact_current_head ON knowledge.intelligence_artifacts "
    "USING btree (principal_id, cycle_run_id, stage, COALESCE(focus_area_id, ''::text), "
    "COALESCE(source_lane, ''::text)) WHERE is_current"
)
HEAD_INDEX_AT: Final = (
    "CREATE UNIQUE INDEX intelligence_artifact_current_head ON knowledge.intelligence_artifacts "
    "USING btree (principal_id, cycle_run_id, stage, artifact_kind, "
    "COALESCE(focus_area_id, ''::text), COALESCE(source_lane, ''::text)) WHERE is_current"
)
WHEN: Final = datetime(2026, 10, 11, 12, tzinfo=UTC)
NEW_CAPABILITIES: Final = ("reports.types.create", "reports.types.list")
BUILTIN_KINDS: Final = tuple(kind.value for kind in ArtifactKind)
FINGERPRINT: Final = "0" * 64

#: (table, server-named inline kind CHECK, declared stage/kind CHECK, key column).
KIND_CHECKS: Final = (
    (
        "intelligence_producer_runs",
        "intelligence_producer_runs_artifact_kind_check",
        "intelligence_run_stage_kind_match",
        "run_id",
    ),
    (
        "intelligence_artifacts",
        "intelligence_artifacts_artifact_kind_check",
        "intelligence_artifact_stage_kind_match",
        "artifact_id",
    ),
)
_WHITESPACE: Final = re.compile(r"\s+")
_LITERAL: Final = re.compile(r"'([^']+)'")


def _config(buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


def _constant(path: Path, name: str) -> object:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not a literal module-level constant of {path.name}")


def _text(path: Path, name: str) -> str:
    value = _constant(path, name)
    assert isinstance(value, str)
    return value


def _flat(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


# ---- FAST: the graph and the freeze -----------------------------------------------


def test_the_revision_is_directly_on_the_project_fields_revision_under_one_later_head() -> None:
    """Re-parented onto `cc373834a485` (#325), which sits on the focus-area revision."""
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [HEAD]
    assert script.get_revision(HEAD).down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision(PREVIOUS).down_revision == "93f3aa113f58"
    assert [path.name for path in VERSIONS.glob(f"*_{REVISION}_*.py")] == [MIGRATION.name]


def test_revision_imports_no_domain_or_persistence_modules() -> None:
    """`D-48`/`D-69`: every vocabulary is frozen text, never derived from an enum."""
    source = MIGRATION.read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported <= {"alembic", "__future__", "typing", "collections.abc"}
    assert "my_pa" not in source
    code = source.split('"""', 2)[2].upper()
    for statement in ("DELETE FROM", "UPDATE {SCHEMA}", "UPDATE KNOWLEDGE", "GRANT ", "TRUNCATE"):
        assert statement not in code


def test_the_capability_before_literal_is_the_knowledge_revisions_at_literal() -> None:
    before = _text(MIGRATION, "_CAPABILITIES_BEFORE_THIS_REVISION")
    assert before == _text(VOCABULARY_MIGRATION, "_CAPABILITIES_AT_THIS_REVISION")
    assert len(_LITERAL.findall(before)) == 201


def test_the_capability_at_literal_adds_exactly_the_two_type_capabilities() -> None:
    before = _LITERAL.findall(_text(MIGRATION, "_CAPABILITIES_BEFORE_THIS_REVISION"))
    at = _LITERAL.findall(_text(MIGRATION, "_CAPABILITIES_AT_THIS_REVISION"))
    assert sorted(set(at) - set(before)) == sorted(NEW_CAPABILITIES)
    assert set(before) <= set(at)
    assert len(at) == len(set(at)) == 203
    assert at == sorted(at)


def test_the_purpose_literals_are_byte_copies_and_unchanged() -> None:
    previous = _text(VOCABULARY_MIGRATION, "_PURPOSES_AT_THIS_REVISION")
    assert _text(MIGRATION, "_PURPOSES_BEFORE_THIS_REVISION") == previous
    assert _text(MIGRATION, "_PURPOSES_AT_THIS_REVISION") == previous


def test_the_kind_before_literals_are_what_the_plane_revision_emitted() -> None:
    def bare(value: str) -> str:
        return _WHITESPACE.sub("", value)

    plane = bare(PLANE_MIGRATION.read_text(encoding="utf-8"))
    kind = _text(MIGRATION, "_KIND_CHECK_BEFORE")
    match = _text(MIGRATION, "_STAGE_KIND_MATCH_BEFORE")
    assert plane.count(f"CHECK({bare(kind)})") == 2
    assert plane.count(f"intelligence_run_stage_kind_matchCHECK({bare(match)})") == 1
    assert plane.count(f"intelligence_artifact_stage_kind_matchCHECK({bare(match)})") == 1
    assert tuple(_LITERAL.findall(kind)) == BUILTIN_KINDS


def test_the_relaxed_checks_keep_every_builtin_pair_and_admit_a_token() -> None:
    at = _flat(_text(MIGRATION, "_STAGE_KIND_MATCH_AT"))
    before = _flat(_text(MIGRATION, "_STAGE_KIND_MATCH_BEFORE"))
    builtins = ", ".join(f"'{kind}'" for kind in BUILTIN_KINDS)
    assert at == f"artifact_kind NOT IN ({builtins}) OR {before}"
    assert _text(MIGRATION, "_KIND_CHECK_AT") == "artifact_kind ~ '^[a-z][a-z0-9_]{0,63}$'"
    assert ARTIFACT_KIND_TOKEN.pattern == r"\A[a-z][a-z0-9_]{0,63}\Z"


def test_the_seeded_builtins_are_the_code_authoritative_definitions() -> None:
    seeds = _constant(MIGRATION, "_BUILTIN_SEEDS")
    definitions = builtin_report_type_definitions()
    assert seeds == tuple(
        (
            str(definition.artifact_kind),
            definition.stage.value,
            definition.description,
            definition.display_name,
            definition.fingerprint,
        )
        for definition in definitions
    )
    pairs = _constant(MIGRATION, "_BUILTIN_PAIRS")
    assert isinstance(pairs, tuple)
    assert tuple((kind.value, stage.value) for kind, stage, _, _ in BUILTIN_REPORT_TYPES) == tuple(
        (kind, stage) for stage, kind in pairs
    )
    assert _constant(MIGRATION, "_BUILTIN_KINDS") == BUILTIN_KINDS


def test_the_downgrade_refusal_names_every_state_the_narrower_schema_cannot_hold() -> None:
    refusal = _flat(_text(MIGRATION, "_REFUSE_DOWNGRADE"))
    assert "FROM knowledge.intelligence_report_types WHERE origin <> 'builtin'" in refusal
    assert "FROM knowledge.intelligence_producer_runs WHERE artifact_kind NOT IN" in refusal
    assert "FROM knowledge.intelligence_artifacts WHERE artifact_kind NOT IN" in refusal
    assert "capability IN ('reports.types.create', 'reports.types.list')" in refusal
    assert "ERRCODE = 'restrict_violation'" in refusal


def test_the_head_index_before_literal_is_what_the_plane_revision_emitted() -> None:
    def bare(value: str) -> str:
        return _WHITESPACE.sub("", value)

    plane = bare(PLANE_MIGRATION.read_text(encoding="utf-8").replace("{SCHEMA}", "knowledge"))
    before = bare(_text(MIGRATION, "_HEAD_INDEX_BEFORE"))
    assert before.startswith(f"CREATEUNIQUEINDEX{HEAD_INDEX}ON")
    assert plane.count(before) == 1
    assert _text(MIGRATION, "HEAD_INDEX") == HEAD_INDEX


def test_the_head_index_at_literal_adds_only_the_kind_after_the_stage() -> None:
    before = _flat(_text(MIGRATION, "_HEAD_INDEX_BEFORE"))
    at = _flat(_text(MIGRATION, "_HEAD_INDEX_AT"))
    assert at == before.replace("stage, coalesce", "stage, artifact_kind, coalesce")
    assert at != before


def test_the_declared_head_index_is_the_at_literal() -> None:
    """The live declaration mirrors the revision (the DDL itself stays frozen text)."""
    (index,) = [i for i in intelligence_artifacts.indexes if i.name == HEAD_INDEX]
    compiled = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    frozen = _text(MIGRATION, "_HEAD_INDEX_AT")
    assert _WHITESPACE.sub("", compiled) + ";" == _WHITESPACE.sub("", frozen)


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


def _checks(engine: Engine) -> dict[tuple[str, str], str]:
    """Every CHECK on the two kind-carrying tables and the audit vocabulary."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT t.relname, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = 'knowledge' AND c.contype = 'c' AND t.relname IN "
                "('intelligence_producer_runs', 'intelligence_artifacts', 'audit_events')"
            )
        ).all()
    return {(str(table), str(name)): str(definition) for table, name, definition in rows}


def _head_index(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = 'knowledge' "
                "AND tablename = 'intelligence_artifacts' AND indexname = :name"
            ),
            {"name": HEAD_INDEX},
        ).scalar_one_or_none()


def _admitted_capabilities(engine: Engine) -> list[str]:
    definition = _checks(engine)[("audit_events", "capability_is_known")]
    return _LITERAL.findall(definition)


def _table_exists(engine: Engine) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT to_regclass('knowledge.intelligence_report_types') IS NOT NULL")
            ).scalar_one()
        )


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


def _seed(engine: Engine, key: str) -> str:
    """One cycle and one collector artifact (with its run) for a fresh Principal."""
    service = _service(engine)
    principal = operator()
    cycle = _ok(
        service,
        principal,
        BeginIntelligenceCycle(
            cycle_id=CYCLE_MORNING_INTELLIGENCE,
            business_date="2026-10-11",
            idempotency_key=f"{key}-cycle",
        ),
    )["cycle_run_id"]
    assert isinstance(cycle, str)
    _ok(
        service,
        principal,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.COLLECTOR,
            artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
            producer_task_id=f"mig-{key}",
            producer_task_name=key,
            automation_platform="abacus_chatllm",
            report_date="2026-10-11",
            title=key,
            body_markdown=f"synthetic {key}",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key=key,
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        ),
    )
    return principal.principal_id


def _registry(engine: Engine) -> set[tuple[str, str, str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT principal_id, artifact_kind, stage, origin "
                "FROM knowledge.intelligence_report_types"
            )
        ).all()
    return {(str(a), str(b), str(c), str(d)) for a, b, c, d in rows}


def _insert_type(
    connection: Connection,
    principal_id: str,
    kind: str,
    *,
    stage: str = "reporter",
    origin: str = "client",
    description: str = "A weekly digest.",
    display_name: str | None = None,
    fingerprint: str = FINGERPRINT,
) -> None:
    connection.execute(
        text(
            "INSERT INTO knowledge.intelligence_report_types (principal_id, artifact_kind, "
            "stage, description, display_name, origin, definition_fingerprint, created_at) "
            "VALUES (:principal, :kind, :stage, :description, :display, :origin, "
            ":fingerprint, :now)"
        ),
        {
            "principal": principal_id,
            "kind": kind,
            "stage": stage,
            "description": description,
            "display": display_name,
            "origin": origin,
            "fingerprint": fingerprint,
            "now": WHEN,
        },
    )


def _refused_type(engine: Engine, principal_id: str, kind: str, **overrides: object) -> str | None:
    """The violated CHECK's name, or None when the row was admitted (rolled back)."""
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            _insert_type(connection, principal_id, kind, **overrides)  # type: ignore[arg-type]
        except DBAPIError as error:
            transaction.rollback()
            assert getattr(error.orig, "sqlstate", None) == CHECK_VIOLATION
            return str(error.orig.diag.constraint_name)  # type: ignore[union-attr]
        transaction.rollback()
        return None


def _copy_with(connection: Connection, table: str, key_column: str, **values: object) -> None:
    """Insert a copy of the one collector row with a fresh key and `values` substituted.

    A copied artifact is not current, so the current-head uniqueness never fires
    before the CHECK under test.
    """
    if table == "intelligence_artifacts":
        values = {"is_current": False, **values}
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
    chosen = []
    for name in columns:
        if name in values:
            chosen.append(f":{name}")
        elif name == key_column:
            chosen.append(f"{name} || 'Zz9'")
        else:
            chosen.append(name)
    inserted = connection.execute(
        text(
            f"INSERT INTO knowledge.{table} ({', '.join(columns)}) "  # noqa: S608
            f"SELECT {', '.join(chosen)} FROM knowledge.{table} "
            "WHERE artifact_kind = 'collector_candidates' LIMIT 1"
        ),
        values,
    )
    assert inserted.rowcount == 1, f"no source row was copied in {table}"


def _refused_copy(engine: Engine, table: str, key_column: str, **values: object) -> str | None:
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            _copy_with(connection, table, key_column, **values)
        except DBAPIError as error:
            transaction.rollback()
            assert getattr(error.orig, "sqlstate", None) == CHECK_VIOLATION
            return str(error.orig.diag.constraint_name)  # type: ignore[union-attr]
        transaction.rollback()
        return None


def _audit(connection: Connection, principal_id: str, capability: str) -> None:
    connection.execute(
        text(
            "INSERT INTO knowledge.audit_events (audit_id, correlation_id, principal_id, "
            "capability, purpose, outcome, policy_version, recorded_at) VALUES "
            "('audit_rtypes0000001', 'corr_rtypes0000001', :principal, :capability, "
            "'report_read', 'allowed', 'policy-v1', :now)"
        ),
        {"principal": principal_id, "capability": capability, "now": WHEN},
    )


@pytest.mark.database
@pytest.mark.migration_edge
def test_the_upgrade_seeds_builtins_for_existing_principals_only(engine: Engine) -> None:
    command.upgrade(_config(), PREVIOUS)
    first = _seed(engine, "rt-first")
    second = _seed(engine, "rt-second")
    command.upgrade(_config(), REVISION)
    assert _version(engine) == REVISION
    expected = {
        (principal, kind.value, stage.value, "builtin")
        for principal in (first, second)
        for kind, stage, _, _ in BUILTIN_REPORT_TYPES
    }
    assert _registry(engine) == expected
    with engine.connect() as connection:
        stored = {
            (str(kind), str(description), display, str(fingerprint))
            for kind, description, display, fingerprint in connection.execute(
                text(
                    "SELECT artifact_kind, description, display_name, definition_fingerprint "
                    "FROM knowledge.intelligence_report_types WHERE principal_id = :principal"
                ),
                {"principal": first},
            )
        }
    assert stored == {
        (
            str(definition.artifact_kind),
            definition.description,
            definition.display_name,
            definition.fingerprint,
        )
        for definition in builtin_report_type_definitions()
    }


@pytest.mark.database
def test_an_empty_plane_seeds_no_rows(engine: Engine) -> None:
    command.upgrade(_config(), REVISION)
    assert _table_exists(engine)
    assert _registry(engine) == set()


@pytest.mark.database
def test_the_declaration_matches_the_migrated_table(engine: Engine) -> None:
    command.upgrade(_config(), REVISION)
    with engine.connect() as connection:
        columns = list(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = "
                    "'knowledge' AND table_name = :table ORDER BY ordinal_position"
                ),
                {"table": TABLE},
            ).scalars()
        )
        constraints = set(
            connection.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'knowledge.intelligence_report_types'::regclass"
                )
            ).scalars()
        )
    assert columns == [column.name for column in intelligence_report_types.columns]
    assert constraints == {constraint.name for constraint in intelligence_report_types.constraints}


@pytest.mark.database
@pytest.mark.parametrize(
    ("kind", "overrides", "constraint"),
    [
        ("Weekly", {}, "intelligence_report_type_kind_is_a_token"),
        ("9weekly", {}, "intelligence_report_type_kind_is_a_token"),
        ("w" * 65, {}, "intelligence_report_type_kind_is_a_token"),
        ("weekly", {"stage": "digest"}, "intelligence_report_type_stage_is_known"),
        ("weekly", {"description": ""}, "intelligence_report_type_description_is_bounded"),
        ("weekly", {"description": "d" * 501}, "intelligence_report_type_description_is_bounded"),
        ("weekly", {"display_name": ""}, "intelligence_report_type_display_name_is_bounded"),
        (
            "weekly",
            {"display_name": "n" * 121},
            "intelligence_report_type_display_name_is_bounded",
        ),
        ("weekly", {"origin": "operator"}, "intelligence_report_type_origin_is_known"),
        ("weekly", {"fingerprint": "ABC"}, "intelligence_report_type_fingerprint_is_sha256"),
        ("weekly", {"origin": "builtin"}, "intelligence_report_type_builtin_is_a_builtin_pair"),
        (
            "focus_report",
            {"origin": "builtin", "stage": "collector"},
            "intelligence_report_type_builtin_is_a_builtin_pair",
        ),
        ("focus_report", {}, "intelligence_report_type_client_is_not_builtin"),
        (
            "morning_brief",
            {"stage": "morning_brief"},
            "intelligence_report_type_client_is_not_builtin",
        ),
    ],
)
def test_the_registry_checks_refuse_each_malformed_row(
    engine: Engine, kind: str, overrides: dict[str, object], constraint: str
) -> None:
    command.upgrade(_config(), REVISION)
    assert _refused_type(engine, "prn_rtypes00000001", kind, **overrides) == constraint


@pytest.mark.database
def test_the_registry_admits_client_and_builtin_rows_and_never_rewrites_one(
    engine: Engine,
) -> None:
    command.upgrade(_config(), REVISION)
    principal = "prn_rtypes00000001"
    assert _refused_type(engine, principal, "weekly_digest", display_name="Weekly") is None
    assert _refused_type(engine, principal, "w" * 64) is None
    assert (
        _refused_type(engine, principal, "focus_report", origin="builtin", stage="reporter") is None
    )
    with engine.begin() as connection:
        _insert_type(connection, principal, "weekly_digest")
    for statement in (
        "UPDATE knowledge.intelligence_report_types SET description = 'changed'",
        "DELETE FROM knowledge.intelligence_report_types",
    ):
        with engine.connect() as connection, pytest.raises(DBAPIError) as refused:
            connection.execute(text(statement))
        assert getattr(refused.value.orig, "sqlstate", None) == RAISE_EXCEPTION


@pytest.mark.database
@pytest.mark.migration_edge
def test_runs_and_artifacts_admit_a_client_kind_but_keep_builtins_on_their_stage(
    engine: Engine,
) -> None:
    command.upgrade(_config(), PREVIOUS)
    _seed(engine, "rt-kinds")
    for table, inline, match, key in KIND_CHECKS:
        # Both CHECKs refuse it here; which one the server reports first is its choice.
        assert _refused_copy(engine, table, key, artifact_kind="weekly_digest") in {inline, match}
    command.upgrade(_config(), REVISION)
    for table, inline, match, key in KIND_CHECKS:
        assert _refused_copy(engine, table, key, artifact_kind="weekly_digest") is None
        assert _refused_copy(engine, table, key, artifact_kind="Weekly Digest") == inline
        # A built-in kind on another stage is still refused by the database.
        assert _refused_copy(engine, table, key, artifact_kind="focus_report") == match
        assert (
            _refused_copy(
                engine, table, key, stage="reporter", artifact_kind="collector_candidates"
            )
            == match
        )


def _refused_head(engine: Engine, **values: object) -> str | None:
    """The SQLSTATE refusing a second *current* artifact at the seeded coordinate, or None."""
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            _copy_with(
                connection, "intelligence_artifacts", "artifact_id", is_current=True, **values
            )
        except DBAPIError as error:
            transaction.rollback()
            return str(getattr(error.orig, "sqlstate", None))
        transaction.rollback()
        return None


@pytest.mark.database
@pytest.mark.migration_edge
def test_the_head_index_is_per_kind_at_this_revision_and_per_stage_before(
    engine: Engine,
) -> None:
    """F1: a client kind is a second head at a built-in coordinate; a built-in still is not."""
    command.upgrade(_config(), PREVIOUS)
    _seed(engine, "rt-heads")
    assert _refused_head(engine) == UNIQUE_VIOLATION
    command.upgrade(_config(), REVISION)
    # The same kind at the same coordinate is still one head ...
    assert _refused_head(engine) == UNIQUE_VIOLATION
    # ... and another kind at that coordinate is its own head.
    assert _refused_head(engine, artifact_kind="weekly_digest") is None
    with engine.begin() as connection:
        _copy_with(
            connection,
            "intelligence_artifacts",
            "artifact_id",
            is_current=True,
            artifact_kind="weekly_digest",
        )
        current = connection.execute(
            text(
                "SELECT artifact_kind FROM knowledge.intelligence_artifacts "
                "WHERE is_current ORDER BY artifact_kind"
            )
        ).scalars()
        assert list(current) == ["collector_candidates", "weekly_digest"]


@pytest.mark.database
def test_a_clean_downgrade_restores_every_check_exactly_and_upgrades_again(
    engine: Engine,
) -> None:
    command.upgrade(_config(), PREVIOUS)
    before = _checks(engine)
    assert _head_index(engine) == HEAD_INDEX_BEFORE
    assert len(_admitted_capabilities(engine)) == 201
    principal = _seed(engine, "rt-round")
    command.upgrade(_config(), REVISION)
    assert _head_index(engine) == HEAD_INDEX_AT
    after = _checks(engine)
    assert set(after) == set(before)
    assert sorted(
        set(_admitted_capabilities(engine))
        - set(_LITERAL.findall(before[("audit_events", "capability_is_known")]))
    ) == sorted(NEW_CAPABILITIES)
    assert len(_admitted_capabilities(engine)) == 203
    assert (
        after[("audit_events", "purpose_is_known")] == before[("audit_events", "purpose_is_known")]
    )
    for table, inline, match, _key in KIND_CHECKS:
        assert after[(table, inline)] != before[(table, inline)]
        assert after[(table, match)] != before[(table, match)]

    command.downgrade(_config(), PREVIOUS)
    assert _version(engine) == PREVIOUS
    assert _checks(engine) == before
    assert _head_index(engine) == HEAD_INDEX_BEFORE
    assert not _table_exists(engine)
    with engine.connect() as connection:
        kept = connection.execute(
            text("SELECT count(*) FROM knowledge.intelligence_artifacts")
        ).scalar_one()
    assert kept == 1

    command.upgrade(_config(), REVISION)
    assert _version(engine) == REVISION
    assert _registry(engine) == {
        (principal, kind.value, stage.value, "builtin")
        for kind, stage, _, _ in BUILTIN_REPORT_TYPES
    }


def _plant_client_type(connection: Connection, principal: str) -> None:
    _insert_type(connection, principal, "weekly_digest")


def _plant_run_kind(connection: Connection, principal: str) -> None:
    del principal
    _copy_with(connection, "intelligence_producer_runs", "run_id", artifact_kind="weekly_digest")


def _plant_artifact_kind(connection: Connection, principal: str) -> None:
    del principal
    _copy_with(connection, "intelligence_artifacts", "artifact_id", artifact_kind="weekly_digest")


def _plant_audit(connection: Connection, principal: str) -> None:
    _audit(connection, principal, "reports.types.list")


def _plant_audit_create(connection: Connection, principal: str) -> None:
    _audit(connection, principal, "reports.types.create")


@pytest.mark.database
@pytest.mark.parametrize(
    "plant",
    [_plant_client_type, _plant_run_kind, _plant_artifact_kind, _plant_audit, _plant_audit_create],
    ids=["client_type", "run_kind", "artifact_kind", "audit_list", "audit_create"],
)
def test_the_downgrade_refuses_while_registry_state_exists(engine: Engine, plant: object) -> None:
    command.upgrade(_config(), REVISION)
    principal = _seed(engine, "rt-refuse")
    with engine.begin() as connection:
        plant(connection, principal)  # type: ignore[operator]
    before = _checks(engine)
    registry = _registry(engine)
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert getattr(refused.value.orig, "sqlstate", None) == RESTRICT_VIOLATION
    assert _version(engine) == REVISION
    assert _checks(engine) == before
    assert _head_index(engine) == HEAD_INDEX_AT
    assert _registry(engine) == registry
