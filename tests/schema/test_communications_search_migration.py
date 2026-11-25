"""Communications intelligence WP4-S1: the communications search revision, `fa18ef3d9bc0`.

`fa18ef3d9bc0` is additive on `0d4e247d03cb` (WP3P). It gives
`communication_messages` the two rederive columns `source_unavailable` and
`identifiers_version` and admits both to the named-mutable trigger (rulings R2,
R3), widens the identifier kind CHECK with `cor` and `pco` (R5) and restates the
audit vocabulary: 312 -> 315 capabilities and 70 -> 71 purposes (D7). Ruling R4
defers the prune: `communication_identifiers` stays append-only exactly as
before. This module proves:

* **the graph** -- this revision is directly on `0d4e247d03cb`; no test here
  names the chain head;
* **the freeze** -- the revision imports nothing from the package it migrates;
  its before texts are byte copies of the revisions that last stated them, and
  its at texts add exactly the new names;
* **offline SQL** for both directions, without a server;
* on a disposable database: the round trip; both columns mutable and the rest
  of the row still frozen; the token CHECK refusing alone; the kind CHECK
  admitting `cor` and `pco` and nothing else; identifiers still append-only;
  the audit vocabulary; each downgrade refusal alone; and the downgrade
  restoring the guard function byte for byte.

The file name routes every test here to migration-edge (`tests/db/fixtures.py`);
the tests with no `database` marker also run in FAST. Every value is synthetic.
"""

from __future__ import annotations

import ast
import io
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, delete, insert, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import (
    audit_events,
    communication_identifiers,
    communication_messages,
    ingest_snapshots,
    ingest_sources,
)

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "fa18ef3d9bc0"
PREVIOUS: Final = "0d4e247d03cb"
MIGRATIONS: Final = ROOT / "migrations" / "versions"
MIGRATION: Final = MIGRATIONS / "20261125_fa18ef3d9bc0_communications_search.py"
PRIOR_CAPABILITY_MIGRATION: Final = MIGRATIONS / "20261123_61fafdfd2986_meeting_sync_staging.py"
PRIOR_PURPOSE_MIGRATION: Final = MIGRATIONS / "20261113_640aaacc78e8_files_workspace.py"
INGESTION_MIGRATION: Final = MIGRATIONS / "20261122_52a829ef718a_communications_ingestion.py"

NEW_CAPABILITIES: Final = frozenset(
    {"communications.coverage", "communications.read", "communications.search"}
)
NEW_PURPOSES: Final = frozenset({"communications_read"})
NEW_COLUMNS: Final = frozenset({"source_unavailable", "identifiers_version"})
VERSION_CHECK: Final = "a_communication_identifiers_version_is_a_token"
KIND_CHECK: Final = "a_communication_identifier_kind_is_known"
GUARD: Final = "communication_messages_change_only_their_projection"

P: Final = "prn_cmsearchmig0001aa"
WHEN: Final = datetime(2026, 11, 25, 12, tzinfo=UTC)
SOURCE: Final = "isrc_cmsearchmig0001"
SNAPSHOT: Final = "isnp_cmsearchmig0001"
MESSAGE: Final = "cmsg_cmsearchmig0001"
_WHITESPACE: Final = re.compile(r"\s+")

RESTRICT_VIOLATION: Final = "23001"
CHECK: Final = "23514"


def _config(buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


def _offline(target: str, *, down: bool = False) -> str:
    buffer = io.StringIO()
    action = command.downgrade if down else command.upgrade
    action(_config(buffer), target, sql=True)
    return _WHITESPACE.sub(" ", buffer.getvalue())


def _source() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _namespace(path: Path) -> dict[str, object]:
    namespace: dict[str, object] = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)  # noqa: S102
    return namespace


def _literals(expression: object) -> list[str]:
    assert isinstance(expression, str)
    return re.findall(r"'([^']+)'", expression)


# ---- the graph and the freeze ------------------------------------------------------


def test_the_revision_is_directly_on_the_project_report_revision() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_revision_imports_no_domain_or_persistence_modules() -> None:
    source = _source()
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported <= {"alembic", "__future__", "typing"}
    assert "my_pa" not in source
    assert "create_all" not in source


def test_the_frozen_literals() -> None:
    code = _source().split('"""', 2)[2]
    assert "SET LOCAL lock_timeout = '10s'" in code
    # D5 / M1: no trigram index. R4: no prune -- no DELETE path, no setting read.
    for absent in ("gin_trgm_ops", "pg_trgm", "current_setting", "DELETE FROM", "GRANT"):
        assert absent not in code, absent
    assert "communication_identifiers_are_append_only" not in code


def test_the_audit_before_texts_are_byte_copies_and_the_at_texts_add_exactly_the_new() -> None:
    mine = _namespace(MIGRATION)
    capabilities = _namespace(PRIOR_CAPABILITY_MIGRATION)
    purposes = _namespace(PRIOR_PURPOSE_MIGRATION)
    assert (
        mine["_CAPABILITIES_BEFORE_THIS_REVISION"] == capabilities["_CAPABILITIES_AT_THIS_REVISION"]
    )
    assert mine["_PURPOSES_BEFORE_THIS_REVISION"] == purposes["_PURPOSES_AT_THIS_REVISION"]
    before = _literals(mine["_CAPABILITIES_BEFORE_THIS_REVISION"])
    at = _literals(mine["_CAPABILITIES_AT_THIS_REVISION"])
    assert (len(before), len(at)) == (312, 315)
    assert at == sorted(at)
    assert set(at) - set(before) == NEW_CAPABILITIES
    assert set(before) <= set(at)
    purposes_before = _literals(mine["_PURPOSES_BEFORE_THIS_REVISION"])
    purposes_at = _literals(mine["_PURPOSES_AT_THIS_REVISION"])
    assert (len(purposes_before), len(purposes_at)) == (70, 71)
    assert purposes_at == sorted(purposes_at)
    assert set(purposes_at) - set(purposes_before) == NEW_PURPOSES
    assert set(purposes_before) <= set(purposes_at)
    assert set(mine["_NEW_CAPABILITIES"]) == NEW_CAPABILITIES  # type: ignore[call-overload]
    assert set(mine["_NEW_PURPOSES"]) == NEW_PURPOSES  # type: ignore[call-overload]


def test_the_guard_before_text_is_the_ingestion_revisions_and_at_adds_exactly_two() -> None:
    mine = _namespace(MIGRATION)
    ingestion = _namespace(INGESTION_MIGRATION)
    assert mine["_MUTABLE_BEFORE_THIS_REVISION"] == ingestion["_MESSAGE_MUTABLE"]
    at = mine["_MUTABLE_AT_THIS_REVISION"]
    assert isinstance(at, tuple)
    assert set(at) - set(ingestion["_MESSAGE_MUTABLE"]) == NEW_COLUMNS  # type: ignore[arg-type]
    # The rendered rule is the ingestion revision's own `_only` for the same set.
    guard = mine["_message_guard"]
    assert callable(guard)
    rendered = guard(ingestion["_MESSAGE_MUTABLE"])
    assert ingestion["_MESSAGE_RULE"] in rendered


def test_the_kind_texts() -> None:
    mine = _namespace(MIGRATION)
    before = _literals(mine["_KINDS_BEFORE_THIS_REVISION"])
    at = _literals(mine["_KINDS_AT_THIS_REVISION"])
    assert before == ["cb", "co", "fpl", "gmp", "rfi", "spec", "submittal"]
    assert at == sorted(at)
    assert set(at) - set(before) == {"cor", "pco"}
    flat = _WHITESPACE.sub(" ", INGESTION_MIGRATION.read_text(encoding="utf-8"))
    assert f"CHECK ({mine['_KINDS_BEFORE_THIS_REVISION']})" in flat


# ---- offline SQL ---------------------------------------------------------------


def test_the_offline_upgrade_locks_first_and_emits_the_whole_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{PREVIOUS}:{REVISION}")
    timeout = rendered.index("SET LOCAL lock_timeout")
    lock = rendered.index(
        "LOCK TABLE knowledge.communication_messages, knowledge.communication_identifiers, "
        "knowledge.audit_events IN ACCESS EXCLUSIVE MODE"
    )
    assert timeout < lock < rendered.index("ALTER TABLE")
    assert rendered.count("LOCK TABLE") == 1
    for column in NEW_COLUMNS:
        assert f"ALTER TABLE knowledge.communication_messages ADD COLUMN {column}" in rendered
    assert "source_unavailable BOOLEAN NOT NULL DEFAULT false" in rendered
    assert f"ADD CONSTRAINT {VERSION_CHECK} CHECK" in rendered
    assert f"CREATE OR REPLACE FUNCTION knowledge.{GUARD}()" in rendered
    assert "CREATE TRIGGER" not in rendered
    assert f"ADD CONSTRAINT {KIND_CHECK} CHECK" in rendered
    assert "'cor'" in rendered and "'pco'" in rendered
    for name in (*NEW_CAPABILITIES, *NEW_PURPOSES):
        assert f"'{name}'" in rendered, name
    assert "GRANT" not in rendered
    assert f"SET version_num='{REVISION}'" in rendered


def test_the_offline_downgrade_refuses_first_and_unwinds_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{REVISION}:{PREVIOUS}", down=True)
    lock = rendered.index("LOCK TABLE knowledge.communication_messages")
    refusal = rendered.index("refusing to downgrade fa18ef3d9bc0")
    assert lock < refusal
    for later in (
        f"DROP CONSTRAINT {KIND_CHECK}",
        "DROP CONSTRAINT capability_is_known",
        "DROP CONSTRAINT purpose_is_known",
        f"CREATE OR REPLACE FUNCTION knowledge.{GUARD}()",
        f"DROP CONSTRAINT {VERSION_CHECK}",
        "DROP COLUMN source_unavailable RESTRICT",
        "DROP COLUMN identifiers_version RESTRICT",
    ):
        assert rendered.index(later) > refusal, later
    assert f"SET version_num='{PREVIOUS}'" in rendered


# ---- disposable databases -------------------------------------------------------


@pytest.fixture
def engine(cloned_database_url: str) -> Iterator[Engine]:
    """A current-head clone, downgraded to this revision (a later one would be unwound)."""
    built = create_database_engine(cloned_database_url)
    command.downgrade(_config(), REVISION)
    try:
        yield built
    finally:
        built.dispose()


def _plant(connection: Connection, **message: object) -> None:
    connection.execute(
        insert(ingest_sources).values(
            ingest_source_id=SOURCE,
            principal_id=P,
            consumer="communications_evidence_v2",
            workspace_id="mcp",
            path_prefix="My PA/Daily Intelligence/",
            file_pattern="*-comms.json",
            enabled=True,
            admitted_at=WHEN,
            admitted_by="operator_cli",
        )
    )
    connection.execute(
        insert(ingest_snapshots).values(
            snapshot_id=SNAPSHOT,
            principal_id=P,
            ingest_source_id=SOURCE,
            file_sha256="a" * 64,
            byte_count=10,
            observed_version_token=None,
            first_seen_at=WHEN,
            status="ingested",
            parser_version="evidence_v2-1.0",
        )
    )
    row: dict[str, object] = {
        "message_id": MESSAGE,
        "principal_id": P,
        "mailbox_ref": "mbx-synthetic",
        "identity_kind": "provider_returned",
        "identity_value": "<m1@example.invalid>",
        "conversation_id": "conv-1",
        "subject": "Pour schedule",
        "sender_address": "a@example.invalid",
        "message_time": WHEN,
        "message_time_basis": "sent",
        "has_attachments": False,
        "body_state": "present",
        "body_sha256": "d" * 64,
        "body_utf8_bytes": 100,
        "content_type": "text",
        "search_text": "The concrete pour for PCO 12",
        "search_text_sha256": "e" * 64,
        "search_text_version": "comms_search_text_v1",
        "search_text_basis": "body_content",
        "search_text_flags": [],
        "text_snapshot_id": SNAPSHOT,
        "text_record_ordinal": 0,
        "first_snapshot_id": SNAPSHOT,
        "latest_snapshot_id": SNAPSHOT,
    }
    connection.execute(insert(communication_messages).values(**{**row, **message}))


@pytest.fixture
def seeded(engine: Engine) -> Engine:
    with engine.begin() as connection:
        _plant(connection)
    return engine


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


def _constraint(error: DBAPIError) -> str | None:
    diag = getattr(error.orig, "diag", None)
    return None if diag is None else diag.constraint_name


def _attempt(
    engine: Engine, statement: Callable[[Connection], Any], *, prelude: str = ""
) -> DBAPIError | None:
    """Run `statement` in a transaction that is always rolled back; return its error."""
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            if prelude:
                connection.execute(text(prelude))
            statement(connection)
        except DBAPIError as error:
            return error
        finally:
            transaction.rollback()
    return None


def _set_message(**values: object) -> Callable[[Connection], Any]:
    return lambda connection: connection.execute(
        update(communication_messages)
        .where(communication_messages.c.message_id == MESSAGE)
        .values(**values)
    )


def _identifier(kind: str, value: str = "12") -> Callable[[Connection], Any]:
    return lambda connection: connection.execute(
        insert(communication_identifiers).values(
            principal_id=P,
            message_id=MESSAGE,
            kind=kind,
            value=value,
            extractor_version="comms_identifiers_v2",
        )
    )


def _audit(capability: str, purpose: str) -> Callable[[Connection], Any]:
    return lambda connection: connection.execute(
        insert(audit_events).values(
            audit_id="audit_cmsearchmigaudit1",
            correlation_id="corr_cmsearchmigaudit1",
            principal_id=P,
            capability=capability,
            purpose=purpose,
            outcome="allowed",
            policy_version="policy-v1",
            scope_source_id_count=0,
            recorded_at=WHEN,
        )
    )


def _columns(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'knowledge' AND table_name = 'communication_messages'"
                )
            ).scalars()
        )


def _guard_source(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text(
                    "SELECT p.prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'knowledge' AND p.proname = :f"
                ),
                {"f": GUARD},
            ).scalar_one()
        )


def _version(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


@pytest.mark.database
def test_the_revision_round_trips_and_restores_the_guard_byte_for_byte(engine: Engine) -> None:
    at = _guard_source(engine)
    assert _columns(engine) >= NEW_COLUMNS
    assert "'source_unavailable', 'identifiers_version'" in at
    command.downgrade(_config(), PREVIOUS)
    assert _version(engine) == PREVIOUS
    assert not _columns(engine) & NEW_COLUMNS
    before = _guard_source(engine)
    assert "source_unavailable" not in before
    # The byte copy: what the downgrade restores is what the ingestion revision built.
    ingestion = _namespace(INGESTION_MIGRATION)
    assert ingestion["_MESSAGE_RULE"] in before  # type: ignore[operator]
    command.upgrade(_config(), REVISION)
    assert _guard_source(engine) == at
    assert _columns(engine) >= NEW_COLUMNS


@pytest.mark.database
def test_the_new_columns_default_and_are_mutable(seeded: Engine) -> None:
    with seeded.begin() as connection:
        row = connection.execute(
            text(
                "SELECT source_unavailable, identifiers_version "
                "FROM knowledge.communication_messages WHERE message_id = :m"
            ),
            {"m": MESSAGE},
        ).one()
        assert tuple(row) == (False, None)
        _set_message(source_unavailable=True)(connection)
        _set_message(identifiers_version="comms_identifiers_v2")(connection)
        _set_message(source_unavailable=False, identifiers_version="comms_identifiers_v3")(
            connection
        )


@pytest.mark.database
@pytest.mark.parametrize(
    ("column", "value"), [("subject", "Rewritten"), ("first_snapshot_id", SNAPSHOT + "x")]
)
def test_the_rest_of_the_row_is_still_frozen(seeded: Engine, column: str, value: object) -> None:
    refused = _attempt(seeded, _set_message(**{column: value}))
    assert refused is not None
    assert _sqlstate(refused) == RESTRICT_VIOLATION
    assert "changes only its named mutable columns" in str(refused)


@pytest.mark.database
def test_the_identifiers_version_token_check_refuses_alone(seeded: Engine) -> None:
    statement = _set_message(identifiers_version="V2 bad")
    refused = _attempt(seeded, statement)
    assert refused is not None
    assert (_sqlstate(refused), _constraint(refused)) == (CHECK, VERSION_CHECK)
    lift = f"ALTER TABLE knowledge.communication_messages DROP CONSTRAINT {VERSION_CHECK}"
    assert _attempt(seeded, statement, prelude=lift) is None


@pytest.mark.database
def test_the_kind_check_admits_cor_and_pco_and_refuses_an_unknown_kind_alone(
    seeded: Engine,
) -> None:
    for kind in ("cor", "pco", "co", "rfi"):
        assert _attempt(seeded, _identifier(kind)) is None, kind
    refused = _attempt(seeded, _identifier("pcox"))
    assert refused is not None
    assert (_sqlstate(refused), _constraint(refused)) == (CHECK, KIND_CHECK)
    lift = f"ALTER TABLE knowledge.communication_identifiers DROP CONSTRAINT {KIND_CHECK}"
    assert _attempt(seeded, _identifier("pcox"), prelude=lift) is None
    command.downgrade(_config(), PREVIOUS)
    for kind in ("cor", "pco"):
        refused = _attempt(seeded, _identifier(kind))
        assert refused is not None
        assert _constraint(refused) == KIND_CHECK


@pytest.mark.database
def test_identifiers_stay_append_only(seeded: Engine) -> None:
    with seeded.begin() as connection:
        _identifier("pco")(connection)
    where = communication_identifiers.c.kind == "pco"
    for statement in (
        lambda c: c.execute(delete(communication_identifiers).where(where)),
        lambda c: c.execute(
            update(communication_identifiers).where(where).values(extractor_version="other")
        ),
    ):
        refused = _attempt(seeded, statement)
        assert refused is not None
        assert _sqlstate(refused) == RESTRICT_VIOLATION
        assert "append-only" in str(refused)


@pytest.mark.database
def test_the_audit_vocabulary_admits_exactly_the_new_names_at_this_revision(
    engine: Engine,
) -> None:
    for name in sorted(NEW_CAPABILITIES):
        assert _attempt(engine, _audit(name, "communications_read")) is None, name
    unknown = _attempt(engine, _audit("communications.unknown", "communications_read"))
    assert unknown is not None
    assert _constraint(unknown) == "capability_is_known"
    unknown = _attempt(engine, _audit("communications.read", "communications_write"))
    assert unknown is not None
    assert _constraint(unknown) == "purpose_is_known"
    command.downgrade(_config(), PREVIOUS)
    for name in sorted(NEW_CAPABILITIES):
        refused = _attempt(engine, _audit(name, "meeting_read"))
        assert refused is not None
        assert _constraint(refused) == "capability_is_known"
    refused = _attempt(engine, _audit("meetings.read", "communications_read"))
    assert refused is not None
    assert _constraint(refused) == "purpose_is_known"


_REFUSALS: Final = {
    "source_unavailable": (
        _set_message(source_unavailable=True),
        "messages record rederive state",
    ),
    "identifiers_version": (
        _set_message(identifiers_version="comms_identifiers_v2"),
        "messages record rederive state",
    ),
    "kind_pco": (_identifier("pco"), "cor or pco identifiers exist"),
    "kind_cor": (_identifier("cor"), "cor or pco identifiers exist"),
    **{
        f"capability_{name}": (
            _audit(name, "meeting_read"),
            "communications audit history exists",
        )
        for name in sorted(NEW_CAPABILITIES)
    },
    "purpose": (
        _audit("meetings.read", "communications_read"),
        "communications audit history exists",
    ),
}


@pytest.mark.database
@pytest.mark.parametrize("case", sorted(_REFUSALS))
def test_a_downgrade_refuses_while_one_row_holds_what_the_previous_revision_cannot(
    seeded: Engine, case: str
) -> None:
    statement, message = _REFUSALS[case]
    with seeded.begin() as connection:
        statement(connection)
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert f"{message}; refusing to downgrade fa18ef3d9bc0" in str(refused.value)
    assert _version(seeded) == REVISION
    assert _columns(seeded) >= NEW_COLUMNS


@pytest.mark.database
def test_a_downgrade_with_only_v1_rows_succeeds_and_keeps_them(seeded: Engine) -> None:
    with seeded.begin() as connection:
        _identifier("rfi")(connection)
    command.downgrade(_config(), PREVIOUS)
    with seeded.connect() as connection:
        kinds = connection.execute(
            text("SELECT kind FROM knowledge.communication_identifiers WHERE message_id = :m"),
            {"m": MESSAGE},
        ).scalars()
        assert list(kinds) == ["rfi"]
