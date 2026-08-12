"""Disposable PostgreSQL proof for GoodNotes review/search and Principal isolation."""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from my_pa.application.goodnotes import GoodNotesService, SourcePage
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.goodnotes.fixture import FixtureGoodNotesSource, FixturePageTranscriber
from my_pa.infrastructure.persistence.goodnotes import (
    PostgresGoodNotesRepository,
    goodnotes_region_proposals,
)

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_goodnotes_test"
WHEN = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"


def administer(engine: Engine, *statements: object) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        administer(maintenance, drop, text(f'CREATE DATABASE "{DATABASE}"'))
        url = configured.set(database=DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        built = create_database_engine(url)
        yield built
        built.dispose()
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        administer(maintenance, drop)
        maintenance.dispose()


def fixture_source() -> FixtureGoodNotesSource:
    return FixtureGoodNotesSource(
        pages=(
            SourcePage(
                principal_id=A,
                source_id="src_aaaaaaaaaaaaaaaaaaaaaaaa",
                source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
                source_version_id="ver_aaaaaaaaaaaaaaaaaaaaaaaa",
                page_number=1,
                observed_at=WHEN,
                content=b"Synthetic handwritten alpha follow-up",
            ),
            SourcePage(
                principal_id=B,
                source_id="src_bbbbbbbbbbbbbbbbbbbbbbbb",
                source_object_id="obj_bbbbbbbbbbbbbbbbbbbbbbbb",
                source_version_id="ver_bbbbbbbbbbbbbbbbbbbbbbbb",
                page_number=1,
                observed_at=WHEN,
                content=b"Synthetic handwritten beta decision",
            ),
        )
    )


def test_two_principals_reconcile_review_correct_and_search_without_an_oracle(
    engine: Engine,
) -> None:
    service = GoodNotesService()
    source = fixture_source()
    receipts = {}
    for principal in (A, B):
        with engine.begin() as connection:
            receipts[principal] = service.reconcile(
                principal_id=principal,
                idempotency_key="initial-sync",
                source=source,
                transcriber=FixturePageTranscriber(),
                repository=PostgresGoodNotesRepository(connection),
            )
    assert receipts[A].page_version_ids != receipts[B].page_version_ids

    with engine.begin() as connection:
        replay = service.reconcile(
            principal_id=A,
            idempotency_key="initial-sync",
            source=source,
            transcriber=FixturePageTranscriber(),
            repository=PostgresGoodNotesRepository(connection),
        )
        region_a = connection.execute(
            select(goodnotes_region_proposals.c.region_id).where(
                goodnotes_region_proposals.c.principal_id == A
            )
        ).scalar_one()
    assert replay.replayed

    # A foreign region and a nonexistent region have the same database-level
    # refusal: neither composite foreign key resolves inside B's partition.
    with pytest.raises(IntegrityError), engine.begin() as connection:
        service.accept_region(
            principal_id=B,
            region_id=region_a,
            corrected_text="must not cross the boundary",
            decided_at=WHEN,
            repository=PostgresGoodNotesRepository(connection),
        )

    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        service.accept_region(
            principal_id=A,
            region_id=region_a,
            corrected_text="Reviewed alpha follow-up",
            decided_at=WHEN,
            repository=repository,
        )
        own = repository.search(A, '"reviewed alpha"', limit=10)
        foreign = repository.search(B, '"reviewed alpha"', limit=10)
    assert len(own) == 1
    assert own[0].corrected
    assert own[0].source_version_id == "ver_aaaaaaaaaaaaaaaaaaaaaaaa"
    assert foreign == ()
