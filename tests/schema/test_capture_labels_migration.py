"""`capture_labels` is append-only and is not a content column."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from my_pa.infrastructure.database.engine import create_database_engine

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "knowledge"
TABLE = "capture_labels"
TRIGGER = "capture_labels_are_append_only"
FUNCTION = "capture_labels_stay_as_written"
REVISION = "c1a8e4d70b29"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.mark.database
def test_head_has_the_append_only_label_table(disposable_database: str) -> None:
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
            triggers = set(
                connection.execute(
                    text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
                ).scalars()
            )
            columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = :schema AND table_name = :table"
                    ),
                    {"schema": SCHEMA, "table": TABLE},
                ).scalars()
            )
        assert TABLE in tables
        assert TRIGGER in triggers
        assert columns == {
            "label_id",
            "capture_id",
            "owner_principal_id",
            "display_label",
            "recorded_at",
        }
        assert "content" not in columns
        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_update_and_delete_of_a_label_row_are_refused(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge.captures (capture_id, owner_principal_id) "
                    "VALUES ('cap_aaaaaaaa11111111', 'prn_aaaaaaaa11111111')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge.capture_labels "
                    "(label_id, capture_id, owner_principal_id, display_label) "
                    "VALUES ('clbl_aaaaaaaa11111111', 'cap_aaaaaaaa11111111', "
                    "'prn_aaaaaaaa11111111', 'Original')"
                )
            )
        for statement in (
            "UPDATE knowledge.capture_labels SET display_label = 'Rewritten' "
            "WHERE label_id = 'clbl_aaaaaaaa11111111'",
            "DELETE FROM knowledge.capture_labels WHERE label_id = 'clbl_aaaaaaaa11111111'",
        ):
            refused: BaseException | None = None
            try:
                with engine.begin() as connection:
                    connection.execute(text(statement))
            except DBAPIError as error:
                refused = error
            assert refused is not None, statement
            assert "append only" in str(refused)
        with engine.connect() as connection:
            remaining = connection.execute(
                text("SELECT display_label FROM knowledge.capture_labels")
            ).scalar_one()
        assert remaining == "Original"
        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


def test_the_revision_is_in_the_chain() -> None:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config())
    assert REVISION in {revision.revision for revision in script.walk_revisions()}
    assert FUNCTION  # named so a rename has to touch this module
