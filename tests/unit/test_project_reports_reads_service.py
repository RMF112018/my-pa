"""WP4P-S3 FAST: the project-report read service over the in-memory fakes.

The shared cases (`tests.unit.project_reports_reads_service_cases`) also run on
PostgreSQL in `tests/database/test_project_reports_reads_service.py`. The
cases here are the service's own: request bounds and their SafeDetail tokens,
and ruling A2 (a reconciliation mismatch qualifies counts, never blocks them)
over a planted mismatch. Every value is synthetic.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest

import my_pa.application.project_reports_reads as reads_module
from my_pa.application.errors import InvalidRequestError, NotFoundError, SafeDetail
from my_pa.application.project_reports_reads import (
    MAX_FILTER_ITEMS,
    MAX_PROJECT_IDS,
    MAX_RECORD_IDS,
    CatalogRequest,
    CompareRequest,
    IdentifierItem,
    QueryRequest,
    RecordHistoryRequest,
)
from tests.unit.project_report_reads_scene import (
    OBS_PROJECT,
    RFI_PROJECT,
    ReadsScene,
    build_world,
    fast_scene,
)
from tests.unit.project_reports_reads_service_cases import CASES, extend_world, service


def _payload(render: Callable[[Any], dict[str, object]]) -> Callable[[Any], Any]:
    """A payload renderer typed `Any`, so a test indexes the JSON it answers."""
    return render


query_payload = _payload(reads_module.query_payload)

PROJECT = RFI_PROJECT[1]


@pytest.fixture
def scene() -> ReadsScene:
    built, _ingest, _world = fast_scene()
    build_world(built)
    extend_world(built)
    return built


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.__name__)
def test_a_service_case_on_the_fake(case: Callable[[ReadsScene], None]) -> None:
    built, _ingest, _world = fast_scene()
    build_world(built)
    extend_world(built)
    case(built)


def _query(**fields: Any) -> QueryRequest:
    base: dict[str, Any] = {"project_id": PROJECT, "record_family": "rfis"}
    base.update(fields)
    return QueryRequest(**base)


@pytest.mark.parametrize(
    ("request_", "detail"),
    [
        (_query(project_id="not-an-id"), SafeDetail.PROJECT_ID),
        (_query(record_family="pulse"), SafeDetail.RECORD_FAMILY),
        (_query(series_id="prser_xyz"), SafeDetail.SERIES_ID),
        (_query(version="isnp_synthetic0001"), SafeDetail.SERIES_ID),
        (_query(status_classes=["shut"]), SafeDetail.STATUS_CLASSES),
        (_query(statuses=["x"] * (MAX_FILTER_ITEMS + 1)), SafeDetail.STATUSES),
        (_query(statuses=[""]), SafeDetail.STATUSES),
        (_query(date_field="rfi.subject"), SafeDetail.DATE_FIELD),
        (_query(date_from=date(2026, 11, 1)), SafeDetail.DATE_FIELD),
        (
            _query(
                date_field="rfi.due_date", date_from=date(2026, 11, 2), date_to=date(2026, 11, 1)
            ),
            SafeDetail.DATE_TO,
        ),
        (_query(date_field="rfi.due_date", date_from="2026-11-01"), SafeDetail.DATE_FROM),
        (_query(identifiers=[IdentifierItem("observation", "1")]), SafeDetail.IDENTIFIERS),
        (_query(identifiers=[IdentifierItem("rfi", "GMP-")]), SafeDetail.IDENTIFIERS),
        (_query(group_keys=["k"] * (MAX_FILTER_ITEMS + 1)), SafeDetail.GROUP_KEYS),
        (_query(text="x" * 201), SafeDetail.TEXT),
        (_query(text="   "), SafeDetail.TEXT),
        (_query(measures=["open_outstanding.rfi.due_date_variance_days"]), SafeDetail.MEASURES),
        (_query(measures=["by_code.adjustment.amount"]), SafeDetail.MEASURES),
        (_query(include_rows="yes"), SafeDetail.INCLUDE_ROWS),
        (_query(limit=0), SafeDetail.LIMIT),
        (_query(limit=101), SafeDetail.LIMIT),
        (_query(cursor="x" * 2049), SafeDetail.CURSOR),
    ],
)
def test_a_query_out_of_bounds_is_invalid_with_one_token(
    scene: ReadsScene, request_: QueryRequest, detail: SafeDetail
) -> None:
    with pytest.raises(InvalidRequestError) as raised:
        service(scene).query(scene.principal, request_)
    assert raised.value.safe_details == (detail,)


def test_the_other_reads_bound_their_requests(scene: ReadsScene) -> None:
    reads = service(scene)
    cases: list[tuple[Callable[[], object], SafeDetail]] = [
        (
            lambda: reads.catalog(
                scene.principal,
                CatalogRequest([f"prj_synreads{i:04d}x" for i in range(MAX_PROJECT_IDS + 1)]),
            ),
            SafeDetail.PROJECT_IDS,
        ),
        (
            lambda: reads.catalog(scene.principal, CatalogRequest([PROJECT, PROJECT])),
            SafeDetail.PROJECT_IDS,
        ),
        (lambda: reads.catalog(scene.principal, CatalogRequest([])), SafeDetail.PROJECT_IDS),
        (
            lambda: reads.catalog(scene.principal, CatalogRequest(record_family="nope")),
            SafeDetail.RECORD_FAMILY,
        ),
        (
            lambda: reads.record_history(
                scene.principal,
                RecordHistoryRequest(
                    record_ids=[f"prrec_syn{i:08d}" for i in range(MAX_RECORD_IDS + 1)]
                ),
            ),
            SafeDetail.RECORD_IDS,
        ),
        (
            lambda: reads.record_history(scene.principal, RecordHistoryRequest()),
            SafeDetail.RECORD_IDS,
        ),
        (
            lambda: reads.record_history(
                scene.principal,
                RecordHistoryRequest(record_ids=["prrec_syn00000001"], project_id=PROJECT),
            ),
            SafeDetail.RECORD_IDS,
        ),
        (
            lambda: reads.record_history(
                scene.principal,
                RecordHistoryRequest(project_id=PROJECT, record_family="rfis", identity_key=" "),
            ),
            SafeDetail.IDENTITY_KEY,
        ),
        (
            lambda: reads.compare(scene.principal, CompareRequest(series_id="x")),
            SafeDetail.SERIES_ID,
        ),
        (
            lambda: reads.compare(
                scene.principal, CompareRequest(series_id="prser_" + "0" * 32, from_version="v1")
            ),
            SafeDetail.FROM_VERSION,
        ),
        (
            lambda: reads.compare(
                scene.principal, CompareRequest(series_id="prser_" + "0" * 32, limit=501)
            ),
            SafeDetail.LIMIT,
        ),
        (
            lambda: reads.match_rfis(scene.principal, PROJECT, [(None, 1)] * 11),
            SafeDetail.IDENTIFIERS,
        ),
    ]
    for call, detail in cases:
        with pytest.raises(InvalidRequestError) as raised:
            call()
        assert raised.value.safe_details == (detail,), detail


def test_a_compare_of_a_one_version_series_is_not_comparable(scene: ReadsScene) -> None:
    reads = service(scene)
    catalog = reads.catalog(scene.principal, CatalogRequest([OBS_PROJECT[1]]))
    (series,) = catalog.projects[0].series
    answer = reads.compare(scene.principal, CompareRequest(series_id=series.series_id))
    assert answer.comparable is False and answer.entries == ()
    with pytest.raises(NotFoundError) as raised:
        reads.compare(
            scene.principal,
            CompareRequest(series_id=series.series_id, from_version="isnp_synthetic00001"),
        )
    assert raised.value.safe_details == (SafeDetail.FROM_VERSION,)


def test_a_reconciliation_mismatch_qualifies_counts_and_never_blocks_them() -> None:
    """Ruling A2, through the service: counts answered and qualified, never blocked."""
    built, _ingest, world = fast_scene()
    build_world(built)
    mismatch = {"column_groups": {"match": 1, "mismatch": 1}, "grand": {"match": 1}}
    derivations = world.project_reports.derivations
    for key, derivation in list(derivations.items()):
        if derivation.project_id == RFI_PROJECT[1]:
            derivations[key] = dataclasses.replace(derivation, reconciliation=mismatch)
    payload = query_payload(
        service(built).query(
            built.principal,
            _query(
                measures=["open_outstanding.record_count", "open_outstanding.row_count"],
                include_rows=False,
            ),
        )
    )
    counts = [m for m in payload["measures"] if m["measure"].endswith("_count")]
    classified = [m for m in counts if m["total"]["state"] == "reportable"]
    assert {m["measure"] for m in classified} == {
        "open_outstanding.record_count",
        "open_outstanding.row_count",
    }
    assert all(m["qualifiers"] == ["reconciliation_mismatch"] for m in classified)
    record_count = next(m for m in classified if m["measure"] == "open_outstanding.record_count")
    assert record_count["total"] == {"state": "reportable", "value": "7"}
