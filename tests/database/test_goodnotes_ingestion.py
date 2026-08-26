"""Disposable PostgreSQL proof for GoodNotes review/search and Principal isolation."""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.sql import Executable

from my_pa.application.goodnotes import GoodNotesService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import ReviewDecisionRequest
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import Disposition, ReviewNotFoundError
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.goodnotes.models import GoodNotesSourceBinding, SourcePage
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
from my_pa.infrastructure.persistence.tables import (
    goodnotes_region_proposals,
    goodnotes_review_decisions,
)

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
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Synthetic shared GoodNotes",
            classification=Classification.SYNTHETIC_TEST,
            native_root="/synthetic/goodnotes/shared",
        )
        observed = observe_object(
            connection,
            source_id=source.source_id,
            native_locator="/synthetic/goodnotes/shared/page.pdf",
            kind=ObjectKind.FILE,
            fingerprint="fingerprint-shared",
            modified_at=WHEN,
            media_type="application/pdf",
            size_bytes=32,
        )
        for principal in (A, B):
            enrollment = accept_enrollment(
                connection,
                EnrollmentRequest(
                    source_id=source.source_id,
                    principal_id=principal,
                    purpose=Purpose.BOUNDED_ENROLLMENT,
                    scope=EnrollmentScope(object_ids=(observed.source_object_id,)),
                    media_types=("text/plain",),
                    policy_version="policy-v1",
                    idempotency_key=f"shared-goodnotes-{principal}",
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

        for ordinal in range(2):
            region_id = f"gregion_b10_{ordinal:018d}"
            review_case_id = issue_identifier(IdKind.REVIEW_CASE)
            connection.execute(
                insert(goodnotes_region_proposals).values(
                    principal_id=A,
                    region_id=region_id,
                    proposal_id=issue_identifier(IdKind.PROPOSAL),
                    review_case_id=review_case_id,
                    page_version_id=case_a.page_version_id,
                    ordinal=100 + ordinal,
                    box={"x": 0, "y": 0, "width": 1, "height": 1},
                    transcription=f"Synthetic prior candidate {ordinal}",
                    confidence=0.5,
                    extractor="synthetic-review-filter",
                    extractor_version="1",
                    opened_at=WHEN - timedelta(minutes=2 - ordinal),
                )
            )
            connection.execute(
                insert(goodnotes_review_decisions).values(
                    principal_id=A,
                    decision_id=issue_identifier(IdKind.REVIEW_DECISION),
                    region_id=region_id,
                    review_case_id=review_case_id,
                    sequence=1,
                    disposition=Disposition.REJECT.value,
                    corrected_text=None,
                    knowledge_id=None,
                    correlation_id=issue_identifier(IdKind.CORRELATION),
                    audit_id=issue_identifier(IdKind.AUDIT),
                    decided_at=WHEN,
                )
            )

        [open_case] = goodnotes_review_cases(
            connection,
            principal_id=A,
            limit=1,
            state=ProposalState.NEEDS_REVIEW,
        )
        assert open_case.review_case_id == case_a.review_case_id

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


def test_goodnotes_manifest_binding_refuses_unregistered_unenrolled_and_mismatched_identity(
    engine: Engine,
) -> None:
    with engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Synthetic admission proof",
            classification=Classification.SYNTHETIC_TEST,
            native_root="/synthetic/goodnotes/admission-proof",
        )
        observed = observe_object(
            connection,
            source_id=source.source_id,
            native_locator="/synthetic/goodnotes/admission-proof/page.pdf",
            kind=ObjectKind.FILE,
            fingerprint="admission-proof-v1",
            modified_at=WHEN,
            media_type="application/pdf",
            size_bytes=32,
        )
        binding = GoodNotesSourceBinding(
            source_id=source.source_id,
            source_object_id=observed.source_object_id,
            source_version_id=observed.version_id,
        )
        repository = PostgresGoodNotesRepository(connection)
        with pytest.raises(ValueError, match="not bound"):
            repository.require_admitted_sources(A, (binding,))

        enrollment = accept_enrollment(
            connection,
            EnrollmentRequest(
                source_id=source.source_id,
                principal_id=A,
                purpose=Purpose.BOUNDED_ENROLLMENT,
                scope=EnrollmentScope(object_ids=(observed.source_object_id,)),
                media_types=("text/plain",),
                policy_version="policy-v1",
                idempotency_key="goodnotes-admission-proof",
                max_items=1,
                max_bytes=1_000_000,
            ),
        ).enrollment
        record_scope(connection, enrollment.enrollment_id, [observed.source_object_id])
        repository.require_admitted_sources(A, (binding,))

        pages = fixture_source(
            principal_id=A,
            source_id=source.source_id,
            object_id=observed.source_object_id,
            version_id=observed.version_id,
        )
        service = GoodNotesService()
        plan = service.plan(
            principal_id=A,
            idempotency_key="collision-proof",
            source=pages,
            transcriber=FixturePageTranscriber(),
        )
        prepared = service.prepare(
            plan=plan,
            source=pages,
            transcriber=FixturePageTranscriber(),
        )
        service.persist(prepared, repository)
        with pytest.raises(ValueError, match="region identity collided"):
            repository.store_reconciliation(
                receipt=prepared.receipt,
                pages=prepared.pages,
                versions=prepared.versions,
                regions=(
                    replace(
                        prepared.regions[0],
                        transcription=prepared.regions[0].transcription + " changed",
                    ),
                ),
            )

        for principal, bad in (
            (B, binding),
            (
                A,
                GoodNotesSourceBinding(
                    source_id="src_cccccccccccccccccccccccc",
                    source_object_id=observed.source_object_id,
                    source_version_id=observed.version_id,
                ),
            ),
            (
                A,
                GoodNotesSourceBinding(
                    source_id=source.source_id,
                    source_object_id="obj_cccccccccccccccccccccccc",
                    source_version_id=observed.version_id,
                ),
            ),
            (
                A,
                GoodNotesSourceBinding(
                    source_id=source.source_id,
                    source_object_id=observed.source_object_id,
                    source_version_id="ver_cccccccccccccccccccccccc",
                ),
            ),
        ):
            with pytest.raises(ValueError, match="not bound"):
                repository.require_admitted_sources(principal, (bad,))
