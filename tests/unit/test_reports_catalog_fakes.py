"""Reports Modernization WP04: the FAST-tier catalog reads keep the SQL semantics.

`FakeUnitOfWork.general_reports.catalog_page` and
`InMemoryIntelligenceStore.catalog_page` stand in for the PostgreSQL reads
(`tests/database/test_reports_general_catalog.py` is the authority). These
tests pin the parts the transport and service suites will lean on: filters,
the default lifecycle, isolation, HEAD-only search, the order, the keyset
(code-point id order, no skip or repeat) and the legacy exclusion rules. The
search is the documented token stand-in (`in_memory_search_rank`).

Every identifier, title and byte is synthetic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Final

import pytest

from my_pa.application.intelligence import InMemoryIntelligenceStore, in_memory_search_rank
from my_pa.contracts.ports import GeneralReportRepository
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.intelligence.catalog import ArtifactKind, ArtifactState, IntelligenceStage
from my_pa.domain.intelligence.models import IntelligenceArtifact, content_digest
from my_pa.domain.reports.catalog import (
    AssociationFilter,
    CatalogCursor,
    CatalogCursorError,
    CatalogFilters,
)
from my_pa.domain.reports.content import validate_content
from my_pa.domain.reports.creator import CreatorKind, ReportCreator, derive_creator
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.publication import PublicationRequest, RequestedAssociation
from my_pa.domain.reports.revision import LifecycleRequest, ReportPatch, UpdateRequest
from my_pa.domain.reports.vocabulary import (
    AssociationTargetKind,
    LifecycleOperation,
    LifecycleState,
)
from my_pa.domain.search.query import SearchQuery
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
T0: Final = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
BINDING: Final = "0" * 64
STANDALONE: Final = AssociationTargetKind.STANDALONE_REPORT


@pytest.fixture
def reports() -> GeneralReportRepository:
    return FakeUnitOfWork(World()).general_reports


def _publish(
    reports: GeneralReportRepository,
    key: str,
    *,
    at: datetime = T0,
    principal_id: str = PRINCIPAL_A,
    title: str = "Plain title",
    body: str = "plain body",
    creator: ReportCreator | None = None,
    **fields: object,
) -> str:
    request = PublicationRequest(
        title=title,
        content=validate_content({"format": "markdown", "body": body}),
        **fields,  # type: ignore[arg-type]
    )
    return reports.publish(
        request,
        principal_id=principal_id,
        creator=creator or derive_creator(CreatorKind.LOCAL_PRINCIPAL, principal_id),
        idempotency_key=key,
        recorded_at=at,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
    ).receipt.report_id


def _ids(
    reports: GeneralReportRepository,
    filters: CatalogFilters | None = None,
    *,
    query: str | None = None,
    after: CatalogCursor | None = None,
    limit: int = 50,
    principal_id: str = PRINCIPAL_A,
) -> list[str]:
    return [
        entry.report_id
        for entry in reports.catalog_page(
            principal_id=principal_id,
            filters=filters or CatalogFilters(),
            query=None if query is None else SearchQuery(query),
            after=after,
            limit=limit,
        )
    ]


def test_the_fake_filters_orders_and_isolates(reports: GeneralReportRepository) -> None:
    a = _publish(
        reports,
        "a",
        at=T0,
        report_type="meeting_note",
        topics=("alpha", "beta"),
        tags=("red",),
        report_date=date(2026, 11, 1),
    )
    b = _publish(reports, "b", at=T0 + timedelta(hours=1), topics=("alpha",))
    c = _publish(
        reports,
        "c",
        at=T0 + timedelta(hours=2),
        associations=(RequestedAssociation(STANDALONE, a, "about"),),
    )
    _publish(reports, "foreign", principal_id=PRINCIPAL_B)
    assert _ids(reports) == [c, b, a]
    assert _ids(reports, CatalogFilters(report_type="meeting_note")) == [a]
    assert _ids(reports, CatalogFilters(topics=("alpha",))) == [b, a]
    assert _ids(reports, CatalogFilters(topics=("alpha", "beta"))) == [a]
    assert _ids(reports, CatalogFilters(tags=("red",))) == [a]
    assert _ids(reports, CatalogFilters(created_from=T0 + timedelta(hours=1))) == [c, b]
    assert _ids(reports, CatalogFilters(created_to=T0 + timedelta(hours=1))) == [a]
    assert _ids(reports, CatalogFilters(report_date_to=date(2026, 12, 1))) == [a]
    linked = CatalogFilters(associated_with=AssociationFilter(STANDALONE, a))
    assert _ids(reports, linked) == [c]
    assert _ids(reports, linked, principal_id=PRINCIPAL_B) == []
    reports.transition(
        LifecycleRequest(LifecycleOperation.ARCHIVE, b, 0),
        principal_id=PRINCIPAL_A,
        idempotency_key="archive-b",
        recorded_at=T0,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
    )
    assert _ids(reports) == [c, a]
    archived = CatalogFilters(lifecycle_states=frozenset({LifecycleState.ARCHIVED}))
    assert _ids(reports, archived) == [b]


def test_the_fake_filters_by_the_root_creator(reports: GeneralReportRepository) -> None:
    remote = derive_creator(CreatorKind.REMOTE_CLIENT, "client-synthetic-0001")
    local = _publish(reports, "local", at=T0)
    by_remote = _publish(reports, "remote", at=T0 + timedelta(hours=1), creator=remote)
    _publish(reports, "foreign", principal_id=PRINCIPAL_B, creator=remote)
    mine = derive_creator(CreatorKind.LOCAL_PRINCIPAL, PRINCIPAL_A).creator_id
    assert _ids(reports, CatalogFilters(created_by=remote.creator_id)) == [by_remote]
    assert _ids(reports, CatalogFilters(created_by=mine)) == [local]
    assert _ids(reports, CatalogFilters(created_by="gcrt_" + "f" * 40)) == []


def test_the_fake_searches_the_head_only_and_ranks_the_title(
    reports: GeneralReportRepository,
) -> None:
    in_body = _publish(reports, "body", at=T0 + timedelta(hours=1), body="the osprey")
    in_title = _publish(reports, "title", title="Osprey survey")
    assert _ids(reports, query="osprey") == [in_title, in_body]
    reports.update(
        UpdateRequest(
            report_id=in_body,
            expected_version=1,
            patch=ReportPatch(content=validate_content({"format": "text", "body": "a heron"})),
            change_reason="Synthetic change.",
        ),
        principal_id=PRINCIPAL_A,
        creator=derive_creator(CreatorKind.LOCAL_PRINCIPAL, PRINCIPAL_A),
        idempotency_key="upd",
        recorded_at=T0 + timedelta(days=1),
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
    )
    assert _ids(reports, query="osprey") == [in_title]
    assert _ids(reports, query="heron") == [in_body]
    assert _ids(reports, query="osprey", principal_id=PRINCIPAL_B) == []


@pytest.mark.parametrize("query", [None, "tern"])
def test_the_fake_keyset_walks_ties_in_code_point_order(
    reports: GeneralReportRepository, query: str | None
) -> None:
    tied = [_publish(reports, f"tie-{n}", title="Tern") for n in range(6)]
    expected = sorted(tied, reverse=True)
    assert _ids(reports, query=query) == expected
    for size in (1, 2, 3):
        seen: list[str] = []
        after: CatalogCursor | None = None
        while True:
            page = reports.catalog_page(
                principal_id=PRINCIPAL_A,
                filters=CatalogFilters(),
                query=None if query is None else SearchQuery(query),
                after=after,
                limit=size + 1,
            )
            seen.extend(entry.report_id for entry in page[:size])
            if len(page) <= size:
                break
            last = page[size - 1]
            after = CatalogCursor(
                binding=BINDING, sort_time=last.created_at, report_id=last.report_id, rank=last.rank
            )
        assert seen == expected, size


def test_the_fake_refuses_a_bad_limit_or_a_mismatched_cursor(
    reports: GeneralReportRepository,
) -> None:
    with pytest.raises(ReportValidationError):
        _ids(reports, limit=0)
    with pytest.raises(ReportValidationError):
        _ids(reports, limit=102)
    search_cursor = CatalogCursor(binding=BINDING, sort_time=T0, report_id="grpt_zzzzzzzz", rank=1)
    with pytest.raises(CatalogCursorError):
        _ids(reports, after=search_cursor)


def _artifact(
    store: InMemoryIntelligenceStore,
    artifact_id: str,
    *,
    at: datetime = T0,
    title: str = "Legacy",
    body: str = "legacy body",
    principal_id: str = PRINCIPAL_A,
    is_current: bool = True,
    artifact_state: ArtifactState = ArtifactState.FINAL,
) -> None:
    store.artifacts[(principal_id, artifact_id)] = IntelligenceArtifact(
        artifact_id=artifact_id,
        principal_id=principal_id,
        cycle_run_id="micr_aaaaaaaa",
        producer_run_id="rrun_aaaaaaaa",
        stage=IntelligenceStage.COLLECTOR,
        artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES.value,
        report_date=date(2026, 11, 1),
        title=title,
        body_markdown=body,
        content_sha256=content_digest(body),
        content_bytes=len(body.encode("utf-8")),
        artifact_state=artifact_state,
        schema_version="1",
        generated_at=at,
        committed_at=at,
        version=1,
        is_current=is_current,
    )


def _legacy(
    store: InMemoryIntelligenceStore,
    filters: CatalogFilters | None = None,
    *,
    query: str | None = None,
    after: CatalogCursor | None = None,
) -> list[str]:
    return [
        artifact.artifact_id
        for artifact, _rank, _snippet in store.catalog_page(
            PRINCIPAL_A,
            filters=filters or CatalogFilters(),
            query=None if query is None else SearchQuery(query),
            after=after,
            limit=50,
        )
    ]


def test_the_in_memory_legacy_catalog_keeps_the_sql_rules() -> None:
    store = InMemoryIntelligenceStore()
    _artifact(store, "rpt_tieAAAA01")
    _artifact(store, "rpt_tieaaaa01", body="the curlew")
    _artifact(store, "rpt_older0001", at=T0 - timedelta(days=1), title="Curlew report")
    _artifact(store, "rpt_stale0001", at=T0 + timedelta(days=1), is_current=False)
    _artifact(store, "rpt_foreign01", principal_id=PRINCIPAL_B)
    assert _legacy(store) == ["rpt_tieaaaa01", "rpt_tieAAAA01", "rpt_older0001"]
    assert _legacy(store, query="curlew") == ["rpt_older0001", "rpt_tieaaaa01"]
    after = CatalogCursor(binding=BINDING, sort_time=T0, report_id="rpt_tieaaaa01")
    assert _legacy(store, after=after) == ["rpt_tieAAAA01", "rpt_older0001"]
    assert _legacy(store, CatalogFilters(report_type="focus_report")) == []
    assert _legacy(store, CatalogFilters(created_to=T0)) == ["rpt_older0001"]
    for excluded in (
        CatalogFilters(topics=("alpha",)),
        CatalogFilters(tags=("red",)),
        CatalogFilters(associated_with=AssociationFilter(STANDALONE, "grpt_anything01")),
        CatalogFilters(lifecycle_states=frozenset({LifecycleState.ARCHIVED})),
        CatalogFilters(
            created_by=derive_creator(CreatorKind.LOCAL_PRINCIPAL, PRINCIPAL_A).creator_id
        ),
    ):
        assert _legacy(store, excluded) == []


def test_the_in_memory_legacy_list_leaves_out_current_superseded_rows() -> None:
    """C2 refinement: list = current and not superseded; search = current."""
    store = InMemoryIntelligenceStore()
    _artifact(store, "rpt_final00001", title="Dunlin")
    _artifact(
        store,
        "rpt_cursuper01",
        at=T0 + timedelta(hours=1),
        title="Dunlin",
        artifact_state=ArtifactState.SUPERSEDED,
    )
    assert _legacy(store) == ["rpt_final00001"]
    assert _legacy(store, query="dunlin") == ["rpt_cursuper01", "rpt_final00001"]


def test_the_token_stand_in_is_deterministic() -> None:
    query = SearchQuery("Osprey nest")
    assert in_memory_search_rank(query, "Osprey nest", ()) == 20
    assert in_memory_search_rank(query, "Osprey", ("a nest", "nest")) == 12
    assert in_memory_search_rank(query, "Osprey", ("no match",)) is None
    assert in_memory_search_rank(SearchQuery("!!"), "anything", ()) is None
