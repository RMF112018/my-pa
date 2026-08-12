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
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.sql import Executable

from my_pa.application.goodnotes import GoodNotesService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import ReviewDecisionRequest
from my_pa.domain.capture.review import Disposition, ReviewNotFoundError
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.goodnotes.models import SourcePage
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.search.query import SearchQuery, SearchRequest
from my_pa.domain.source.enrollment import EnrollmentRequest, EnrollmentScope
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind, issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.goodnotes.fixture import FixtureGoodNotesSource, FixturePageTranscriber
from my_pa.infrastructure.persistence.enrollment import accept_enrollment, record_scope
from my_pa.infrastructure.persistence.goodnotes import (
    PostgresGoodNotesRepository,
    decide_goodnotes_review,
    goodnotes_review_cases,
)
from my_pa.infrastructure.persistence.registry import observe_object, register_source
from my_pa.infrastructure.persistence.search import search_extractions

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_goodnotes_test"
WHEN = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"


def administer(engine: Engine, *statements: Executable) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)


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


def fixture_source(
    *, principal_id: str, source_id: str, object_id: str, version_id: str
) -> FixtureGoodNotesSource:
    return FixtureGoodNotesSource(
        pages=(
            SourcePage(
                principal_id=principal_id,
                source_id=source_id,
                source_object_id=object_id,
                source_version_id=version_id,
                page_number=1,
                observed_at=WHEN,
                content=b"Synthetic handwritten alpha follow-up",
            ),
        )
    )


def test_two_principals_reconcile_review_correct_and_search_without_an_oracle(
    engine: Engine,
) -> None:
    service = GoodNotesService()
    scopes: dict[str, tuple[FixtureGoodNotesSource, str]] = {}
    with engine.begin() as connection:
        for principal in (A, B):
            source = register_source(
                connection,
                provider_kind=SourceProviderKind.FIXTURE,
                label="Synthetic GoodNotes",
                classification=Classification.SYNTHETIC_TEST,
                native_root=f"/synthetic/goodnotes/{principal}",
            )
            observed = observe_object(
                connection,
                source_id=source.source_id,
                native_locator=f"/synthetic/goodnotes/{principal}/page.pdf",
                kind=ObjectKind.FILE,
                fingerprint=f"fingerprint-{principal}",
                modified_at=WHEN,
                media_type="application/pdf",
                size_bytes=32,
            )
            enrollment = accept_enrollment(
                connection,
                EnrollmentRequest(
                    source_id=source.source_id,
                    principal_id=principal,
                    purpose=Purpose.BOUNDED_ENROLLMENT,
                    scope=EnrollmentScope(object_ids=(observed.source_object_id,)),
                    media_types=("text/plain",),
                    policy_version="policy-v1",
                    idempotency_key=f"goodnotes-{principal}",
                    max_items=1,
                    max_bytes=1_000_000,
                ),
            ).enrollment
            record_scope(connection, enrollment.enrollment_id, [observed.source_object_id])
            pages = fixture_source(
                principal_id=principal,
                source_id=source.source_id,
                object_id=observed.source_object_id,
                version_id=observed.version_id,
            )
            service.reconcile(
                principal_id=principal,
                idempotency_key="initial-sync",
                source=pages,
                transcriber=FixturePageTranscriber(),
                repository=PostgresGoodNotesRepository(connection),
            )
            scopes[principal] = (pages, enrollment.enrollment_id)

    with engine.begin() as connection:
        [case_a] = goodnotes_review_cases(connection, principal_id=A, limit=10)
        assert goodnotes_review_cases(connection, principal_id=B, limit=10)[0].review_case_id != (
            case_a.review_case_id
        )
        with pytest.raises(ReviewNotFoundError):
            decide_goodnotes_review(
                connection,
                ReviewDecisionRequest(
                    review_case_id=case_a.review_case_id,
                    expected_review_version=0,
                    disposition=Disposition.ACCEPT,
                    principal_id=B,
                    correlation_id=issue_identifier(IdKind.CORRELATION),
                    audit_id=issue_identifier(IdKind.AUDIT),
                    policy_version="policy-v1",
                    decided_at=WHEN,
                ),
            )

    with engine.begin() as connection:
        decision = decide_goodnotes_review(
            connection,
            ReviewDecisionRequest(
                review_case_id=case_a.review_case_id,
                expected_review_version=0,
                disposition=Disposition.CORRECT_AND_ACCEPT,
                principal_id=A,
                correlation_id=issue_identifier(IdKind.CORRELATION),
                audit_id=issue_identifier(IdKind.AUDIT),
                policy_version="policy-v1",
                decided_at=WHEN,
                corrected_value="Reviewed alpha follow-up",
            ),
        )
        assert decision.review_case_id == case_a.review_case_id
        own = search_extractions(
            connection,
            SearchRequest(enrollment_id=scopes[A][1], query=SearchQuery('"reviewed alpha"')),
            now=WHEN,
        )
        foreign = search_extractions(
            connection,
            SearchRequest(enrollment_id=scopes[B][1], query=SearchQuery('"reviewed alpha"')),
            now=WHEN,
        )
    assert len(own.matches) == 1
    assert own.matches[0].version_id.startswith("ver_")
    assert foreign.matches == ()
