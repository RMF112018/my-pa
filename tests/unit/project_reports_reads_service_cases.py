"""The WP4P-S3 read-service cases, run against the FAST fake and against PostgreSQL.

Each case takes a `ReadsScene` built by `build_world` and then `extend_world`
(every value synthetic) and asserts through `ProjectReportReads` alone.
`tests/unit/test_project_reports_reads_service.py` runs them over the fakes;
`tests/database/test_project_reports_reads_service.py` over a head-migrated
clone.

`extend_world` adds, in one fixed order under the scene's clock:

* 2 more RFI views of the `qxrfis` Project (a record observed in 3 views);
* a buyout and a reconciliation export of one date label whose cross-report
  check mismatches (the buyout's approved prime change is `$310.00` against
  the reconciliation's `$300.00`), each internally reconciled, in one source;
* a Project whose only version is quarantined, and one bound but never ingested.

The ruling B1 (amended) cases bind their own reconciliation Projects inside
the case (`_reconciliation_project`): one whose stated totals all match and
one whose grand total is planted `$1.00` off.
"""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Final

import pytest

import my_pa.application.project_reports_reads as reads_module
from my_pa.application.errors import (
    ApplicationError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.application.project_reports_ingest import DerivedExport
from my_pa.application.project_reports_reads import (
    CatalogRequest,
    CompareRequest,
    CoverageRequest,
    IdentifierItem,
    ProjectReportReads,
    QueryRequest,
    RecordHistoryRequest,
)
from my_pa.application.project_reports_rederive import ProjectReportsRederiver
from my_pa.bootstrap.project_reports import PulseExportReader
from my_pa.domain.project_reports.catalogue import MEASURES
from my_pa.domain.project_reports.model import FamilyView, ReconciliationOutcome
from my_pa.domain.project_reports.reconciliation import CrossReportCheck
from tests.unit.project_report_reads_scene import (
    NOTE_PROJECT,
    OBS_PROJECT,
    RFI_PROJECT,
    ReadsScene,
    adapter,
    csv_bytes,
    quarantined_export,
    rfi_export,
)
from tests.unit.project_reports_scene import FIXTURES


def _payload(render: Callable[[Any], dict[str, object]]) -> Callable[[Any], Any]:
    """A payload renderer typed `Any`, so a test indexes the JSON it answers."""
    return render


catalog_payload = _payload(reads_module.catalog_payload)
compare_payload = _payload(reads_module.compare_payload)
coverage_payload = _payload(reads_module.coverage_payload)
project_summary_payload = _payload(reads_module.project_summary_payload)
query_payload = _payload(reads_module.query_payload)
record_history_payload = _payload(reads_module.record_history_payload)

OTHER_PRINCIPAL: Final = "prn_synotherreads01"
NOW: Final = datetime(2026, 12, 1, tzinfo=UTC)

#: The cross-checked pair's Project: `(key, project_id, number)`, one source for both exports.
PAIR_PROJECT: Final = ("pair", "prj_synreads0004x", "SYN-0001")
QUARANTINED_PROJECT: Final = ("quarantined", "prj_synreads0005x", "SYN-7105")
NEVER_PROJECT: Final = ("never", "prj_synreads0006x", "SYN-7106")
UNKNOWN_PROJECT: Final = "prj_synreads0099x"
#: Ruling B1 (amended): a reconciled reconciliation export, and one whose grand total mismatches.
SOLO_PROJECT: Final = ("solo", "prj_synreads0007x", "SYN-7107")
MISMATCH_PROJECT: Final = ("mismatch", "prj_synreads0008x", "SYN-7108")
PRIME: Final = "reconciliation.prime_co_line.amount"
COMMITMENT: Final = "reconciliation.commitment_co_line.amount"

#: A later readable `qxrfiq` version (ruling B2: its quarantined predecessor is the `from` side).
QUARANTINE_ROWS_LATER: Final = (
    ("GMP-201", "Synthetic hotel", "", "", "11/1/2026", "", ""),
    ("GMP-203", "Synthetic kilo", "", "", "11/2/2026", "", ""),
)

LINKED: Final = "20261121-qxrfilinks.csv"
CLOSED: Final = "20261122-qxrficlosed.csv"
NEXT_RFI: Final = "20261125-qxrfis.csv"


def service(scene: ReadsScene, *, reads_enabled: bool = True) -> ProjectReportReads:
    return ProjectReportReads(
        unit_of_work=scene.unit, clock=lambda: NOW, reads_enabled=reads_enabled
    )


def _signature_bytes(view: str) -> bytes:
    return (FIXTURES / "signatures" / f"{view}.csv").read_bytes()


def extend_world(scene: ReadsScene) -> None:
    linked = adapter(FamilyView.LINKED_TO_DRAWINGS).header
    closed = adapter(FamilyView.RECENTLY_CLOSED).header
    scene.ingest(
        "rfis",
        LINKED,
        csv_bytes(
            linked,
            [
                ("GMP-174", "Synthetic alpha", "SYN-A1", "1", "Pin", "Link"),
                ("GMP-174", "Synthetic alpha", "SYN-A2", "1", "Pin", "Link"),
            ],
        ),
    )
    scene.ingest(
        "rfis",
        CLOSED,
        csv_bytes(closed, [("GMP-174", "Synthetic alpha", "High", "11/1/2026", "11/21/2026", "1")]),
    )
    scene.bind(*PAIR_PROJECT)
    buyout = _signature_bytes("buyout_summary").replace(b"$300.00", b"$310.00")
    scene.ingest(PAIR_PROJECT[0], "20261118-qxbuyout.csv", buyout)
    scene.ingest(PAIR_PROJECT[0], "20261118-qxrecon.csv", _signature_bytes("reconciliation"))
    scene.bind(*QUARANTINED_PROJECT)
    scene.ingest(QUARANTINED_PROJECT[0], "20261115-qxonlyq.csv", quarantined_export())
    scene.bind(*NEVER_PROJECT)


class FixedBuyoutReader(PulseExportReader):
    """A later buyout adapter version whose reading now agrees with the reconciliation.

    Only the buyout signature's version moves, so a sweep re-derives the buyout
    alone (`rederive_version`) and writes a new, matching check against the
    reconciliation; the first check, naming the superseded buyout, stays stored.
    """

    def adapter_version(self, header_signature: str) -> str | None:
        version = super().adapter_version(header_signature)
        if header_signature == adapter(FamilyView.BUYOUT_SUMMARY).signature:
            return f"{version}_synthetic_fix"
        return version

    def cross_report(
        self, buyout: DerivedExport, reconciliation: DerivedExport
    ) -> CrossReportCheck:
        found = super().cross_report(buyout, reconciliation)
        return dataclasses.replace(
            found, left_value=found.right_value, outcome=ReconciliationOutcome.MATCH
        )


def rederive_the_buyout_alone(scene: ReadsScene) -> None:
    ProjectReportsRederiver(
        unit_of_work=scene.unit, reader=FixedBuyoutReader(), clock=scene.clock
    ).sweep(scene.principal)


def _refusal(call: Callable[[], object]) -> tuple[type[ApplicationError], tuple[SafeDetail, ...]]:
    with pytest.raises(ApplicationError) as raised:
        call()
    return type(raised.value), raised.value.safe_details


def _rfi_query(scene: ReadsScene, **fields: object) -> QueryRequest:
    return QueryRequest(project_id=RFI_PROJECT[1], record_family="rfis", **fields)


def _series_of(scene: ReadsScene, slug: str, project: str = RFI_PROJECT[1]) -> str:
    answer = catalog_payload(service(scene).catalog(scene.principal, CatalogRequest([project])))
    projects = answer["projects"]
    assert isinstance(projects, list)
    found = [s["series_id"] for s in projects[0]["series"] if s["slug_label"] == slug]
    assert len(found) == 1, found
    return str(found[0])


def _measure(payload: dict[str, object], name: str) -> dict[str, object]:
    measures = payload["measures"]
    assert isinstance(measures, list)
    found = [m for m in measures if m["measure"] == name]
    assert len(found) == 1, found
    return dict(found[0])


def _reconciliation_project(scene: ReadsScene, project: tuple[str, str, str]) -> None:
    """Bind `project` and ingest the synthetic reconciliation (grand total off for `mismatch`)."""
    data = _signature_bytes("reconciliation")
    if project is MISMATCH_PROJECT:
        planted = data.replace(b"Grand Totals,,,,,$350.00", b"Grand Totals,,,,,$351.00")
        assert planted != data
        data = planted
    scene.bind(*project)
    scene.ingest(project[0], f"20261118-qx{project[0]}.csv", data)


def _reconciliation_query(project: tuple[str, str, str], **fields: object) -> QueryRequest:
    return QueryRequest(
        project_id=project[1],
        record_family="change_order_reconciliation",
        measures=(PRIME, COMMITMENT),
        **fields,
    )


def _amounts(payload: dict[str, object], name: str) -> dict[str, object]:
    """`{status: amount}` of a reportable per-status measure, `{status: reasons}` otherwise."""
    by_status = _measure(payload, name)["by_status"]
    assert isinstance(by_status, dict)
    return {
        status: value["value"]["amount"] if value["state"] == "reportable" else value["reasons"]
        for status, value in by_status.items()
    }


_FROM_JUNE_2: Final = {"date_field": "pco.date_created", "date_from": date(2026, 6, 2)}


# --- cases ------------------------------------------------------------------------------


def case_catalog_lists_series_with_their_latest_version(scene: ReadsScene) -> None:
    payload = catalog_payload(
        service(scene).catalog(scene.principal, CatalogRequest([RFI_PROJECT[1]]))
    )
    (project,) = payload["projects"]
    assert project["project_number"] == RFI_PROJECT[2]
    assert project["currency"] == "USD"
    slugs = sorted(s["slug_label"] for s in project["series"])
    assert slugs == ["qxrficlosed", "qxrfilinks", "qxrfiq", "qxrfis"]
    quarantined = next(s for s in project["series"] if s["slug_label"] == "qxrfiq")
    assert quarantined["quarantined_versions"] == 1
    assert quarantined["latest"]["derivation_state"] == "quarantined"
    assert quarantined["latest"]["is_latest"] is True
    rfis = next(s for s in project["series"] if s["slug_label"] == "qxrfis")
    assert rfis["latest"]["publication_date"] == "2026-11-20"
    assert len(rfis["signature_prefix"]) == 8
    assert "open_outstanding.rfi.due_date_variance_days" not in rfis["measures_available"]
    assert "open_outstanding.record_count" in rfis["measures_available"]
    assert payload["qualifiers"] == ["filter_semantics_unknown"]


def case_query_pages_are_disjoint_and_complete(scene: ReadsScene) -> None:
    reads = service(scene)
    series = _series_of(scene, "qxrfis")
    seen: list[tuple[str, int]] = []
    cursor: str | None = None
    for _page in range(10):
        payload = query_payload(
            reads.query(
                scene.principal, _rfi_query(scene, series_id=series, limit=3, cursor=cursor)
            )
        )
        rows = payload["rows"]
        assert isinstance(rows, list)
        seen += [(r["version"], r["row_ordinal"]) for r in rows]
        cursor = payload["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 7
    whole = query_payload(
        reads.query(scene.principal, _rfi_query(scene, series_id=series, limit=100))
    )
    assert [(r["version"], r["row_ordinal"]) for r in whole["rows"]] == seen


def case_a_new_version_between_pages_restarts(scene: ReadsScene) -> None:
    """Ruling D4 (b): the resolved version set changed, so nothing else is answered."""
    reads = service(scene)
    request = _rfi_query(scene, limit=2)
    first = query_payload(reads.query(scene.principal, request))
    assert first["next_cursor"] is not None
    scene.ingest(
        "rfis", NEXT_RFI, rfi_export((("GMP-180", "Synthetic juliet", "", "", "", "", ""),))
    )
    second = query_payload(
        reads.query(scene.principal, dataclasses.replace(request, cursor=first["next_cursor"]))
    )
    assert second == {
        "rows": [],
        "rfi_match": [],
        "measures": [],
        "versions": [],
        "qualifiers": [],
        "next_cursor": None,
        "cursor_state": "scope_changed_restart_required",
    }


def case_a_cursor_of_another_request_or_principal_is_a_conflict(scene: ReadsScene) -> None:
    reads = service(scene)
    first = query_payload(reads.query(scene.principal, _rfi_query(scene, limit=2)))
    token = first["next_cursor"]
    assert isinstance(token, str)
    changed = _rfi_query(scene, limit=2, text="synthetic", cursor=token)
    assert _refusal(lambda: reads.query(scene.principal, changed)) == (
        ConflictError,
        (SafeDetail.CURSOR,),
    )
    assert _refusal(
        lambda: reads.query(OTHER_PRINCIPAL, _rfi_query(scene, limit=2, cursor=token))
    ) == (ConflictError, (SafeDetail.CURSOR,))
    assert _refusal(
        lambda: reads.query(scene.principal, _rfi_query(scene, limit=2, cursor="AAAA"))
    ) == (InvalidRequestError, (SafeDetail.CURSOR,))
    # A changed grant set is a changed scope.
    regranted = reads.query(
        scene.principal,
        _rfi_query(scene, limit=2, cursor=token),
        grants=[("project_reports.query", None)],
    )
    assert regranted.cursor_state == "scope_changed_restart_required"


def case_source_totals_are_never_measures(scene: ReadsScene) -> None:
    """PULSE-AC-08 part 2: stated totals are evidence only, never a measure."""
    reads = service(scene)
    names = tuple(n for n, spec in MEASURES.items() if spec.view is FamilyView.RECONCILIATION)
    payload = query_payload(
        reads.query(
            scene.principal,
            QueryRequest(
                project_id=PAIR_PROJECT[1],
                record_family="change_order_reconciliation",
                measures=names,
                include_rows=False,
            ),
        )
    )
    measures = payload["measures"]
    assert isinstance(measures, list)
    assert {m["measure"] for m in measures} == set(names)
    assert all(set(m) >= {"measure", "basis", "total", "by_status"} for m in measures)
    totals = payload["source_totals"]
    assert isinstance(totals, dict) and totals["basis"] == "source_evidence"
    assert totals["entries"], "the stated totals are answered as evidence"
    stated = {(e["field_key"], e["raw_text"]) for e in totals["entries"]}
    assert not {m["measure"] for m in measures} & {f for f, _ in stated}
    assert payload["rows"] == []


def case_a_cross_check_mismatch_withholds_both_columns(scene: ReadsScene) -> None:
    reads = service(scene)
    buyout = query_payload(
        reads.query(
            scene.principal,
            QueryRequest(
                project_id=PAIR_PROJECT[1],
                record_family="buyout",
                measures=(
                    "buyout_summary.prime_co_line.approved_amount",
                    "buyout_summary.budget_change_line.amount",
                ),
                include_rows=False,
            ),
        )
    )
    checked = _measure(buyout, "buyout_summary.prime_co_line.approved_amount")
    assert checked["total"] == {"state": "not_reportable", "reasons": ["reconciliation_mismatch"]}
    other = _measure(buyout, "buyout_summary.budget_change_line.amount")
    assert other["total"] == {
        "state": "reportable",
        "value": {"amount": "75.00", "currency": "USD"},
    }
    reconciliation = query_payload(
        reads.query(
            scene.principal,
            QueryRequest(
                project_id=PAIR_PROJECT[1],
                record_family="change_order_reconciliation",
                measures=("reconciliation.prime_co_line.amount",),
                include_rows=False,
            ),
        )
    )
    by_status = _measure(reconciliation, "reconciliation.prime_co_line.amount")["by_status"]
    assert isinstance(by_status, dict)
    assert by_status["approved"] == {
        "state": "not_reportable",
        "reasons": ["reconciliation_mismatch"],
    }


def case_a_stale_cross_check_is_ignored_after_a_rederivation(scene: ReadsScene) -> None:
    """Ruling A4: the buyout alone is re-derived, so the first check is stale."""
    with scene.unit() as unit:
        checks_before = len(
            unit.project_reports.list_cross_checks(scene.principal, PAIR_PROJECT[1])
        )
    rederive_the_buyout_alone(scene)
    with scene.unit() as unit:
        checks = unit.project_reports.list_cross_checks(scene.principal, PAIR_PROJECT[1])
    # The stale mismatch is still stored beside the new match.
    assert checks_before == 1
    assert sorted(c.outcome.value for c in checks) == ["match", "mismatch"]
    reads = service(scene)
    buyout = query_payload(
        reads.query(
            scene.principal,
            QueryRequest(
                project_id=PAIR_PROJECT[1],
                record_family="buyout",
                measures=("buyout_summary.prime_co_line.approved_amount",),
                include_rows=False,
            ),
        )
    )
    assert _measure(buyout, "buyout_summary.prime_co_line.approved_amount")["total"] == {
        "state": "reportable",
        "value": {"amount": "310.00", "currency": "USD"},
    }
    reconciliation = query_payload(
        reads.query(
            scene.principal,
            QueryRequest(
                project_id=PAIR_PROJECT[1],
                record_family="change_order_reconciliation",
                measures=("reconciliation.prime_co_line.amount",),
                include_rows=False,
            ),
        )
    )
    by_status = _measure(reconciliation, "reconciliation.prime_co_line.amount")["by_status"]
    assert isinstance(by_status, dict)
    assert by_status["approved"] == {
        "state": "reportable",
        "value": {"amount": "300.00", "currency": "USD"},
    }


def case_record_history_spans_three_rfi_views(scene: ReadsScene) -> None:
    payload = record_history_payload(
        service(scene).record_history(
            scene.principal,
            RecordHistoryRequest(
                project_id=RFI_PROJECT[1], record_family="rfis", identity_key="rfi:GMP-174"
            ),
        )
    )
    (record,) = payload["records"]
    views = [o["family_view"] for o in record["observations"]]
    assert sorted(set(views)) == ["linked_to_drawings", "open_outstanding", "recently_closed"]
    assert views.count("open_outstanding") == 2
    assert views.count("linked_to_drawings") == 2
    outstanding = [o for o in record["observations"] if o["family_view"] == "open_outstanding"]
    # The earlier version (D10) first; the later one changed the ball in court.
    assert [o["changed_fields"] for o in outstanding] == [[], ["rfi.ball_in_court"]]
    assert all(s["presence"] == "observed_in_latest" for s in record["series"])
    assert len(record["series"]) == 3
    by_id = record_history_payload(
        service(scene).record_history(
            scene.principal, RecordHistoryRequest(record_ids=[record["record_id"]])
        )
    )
    assert by_id["records"] == payload["records"]


def _linked(scene: ReadsScene, name: str, drawings: tuple[str, ...]) -> None:
    header = adapter(FamilyView.LINKED_TO_DRAWINGS).header
    rows = [("GMP-174", "Synthetic alpha", drawing, "1", "Pin", "Link") for drawing in drawings]
    scene.ingest("rfis", name, csv_bytes(header, rows))


def case_changed_fields_compare_consecutive_versions_only(scene: ReadsScene) -> None:
    """Ruling R1-06: never two lines of one version; several lines compare as a multiset."""
    # The same two links in the other order, then one link replaced.
    _linked(scene, "20261123-qxrfilinks.csv", ("SYN-A2", "SYN-A1"))
    _linked(scene, "20261124-qxrfilinks.csv", ("SYN-A1", "SYN-A3"))

    def linked() -> list[tuple[str, list[str], str | None]]:
        payload = record_history_payload(
            service(scene).record_history(
                scene.principal,
                RecordHistoryRequest(
                    project_id=RFI_PROJECT[1], record_family="rfis", identity_key="rfi:GMP-174"
                ),
            )
        )
        (record,) = payload["records"]
        dates = {v["version"]: v["publication_date"] for v in payload["versions"]}
        return [
            (
                dates[o["version"]],
                o["changed_fields"],
                None if o["changed_since_version"] is None else dates[o["changed_since_version"]],
            )
            for o in record["observations"]
            if o["family_view"] == "linked_to_drawings"
        ]

    assert [(when, changed) for when, changed, _since in linked()] == [
        # Two lines of one version are never a change of each other.
        ("2026-11-21", []),
        ("2026-11-21", []),
        # The same multiset of links in another order: no change.
        ("2026-11-23", []),
        ("2026-11-23", []),
        # One link replaced: answered once, on the version's first line.
        ("2026-11-24", ["rfi.drawing_number"]),
        ("2026-11-24", []),
    ]
    # Ruling R2-07: the first line of each version names its baseline (the
    # previous observation's version); the other lines name none.
    assert [(when, since) for when, _changed, since in linked()] == [
        ("2026-11-21", None),
        ("2026-11-21", None),
        ("2026-11-23", "2026-11-21"),
        ("2026-11-23", None),
        ("2026-11-24", "2026-11-23"),
        ("2026-11-24", None),
    ]


def case_changed_since_names_the_readable_baseline_across_a_gap(scene: ReadsScene) -> None:
    """Ruling R2-07: across an unreadable version, `changed_fields` names its baseline.

    v1 classified, v2 quarantined, v3 classified with a changed subject: v3's
    change is judged against v1 (nothing is inferred from v2), and
    `changed_since_version` says so.
    """
    changed = (("GMP-201", "Synthetic hotel changed", "", "", "11/1/2026", "", ""),)
    scene.ingest("rfis", "20261130-qxrfiq.csv", rfi_export(changed))
    payload = record_history_payload(
        service(scene).record_history(
            scene.principal,
            RecordHistoryRequest(
                project_id=RFI_PROJECT[1], record_family="rfis", identity_key="rfi:GMP-201"
            ),
        )
    )
    dates = {v["version"]: v["publication_date"] for v in payload["versions"]}
    (record,) = payload["records"]
    assert [
        (dates[o["version"]], o["changed_fields"], o["changed_since_version"])
        for o in record["observations"]
    ] == [
        ("2026-11-01", [], None),
        ("2026-11-30", ["rfi.subject"], next(k for k, d in dates.items() if d == "2026-11-01")),
    ]


def case_an_absent_record_is_not_observed_never_closed(scene: ReadsScene) -> None:
    """PULSE-AC-11: absent from the latest version is `not_observed`, never closed."""
    reads = service(scene)
    history = record_history_payload(
        reads.record_history(
            scene.principal,
            RecordHistoryRequest(
                project_id=RFI_PROJECT[1], record_family="rfis", identity_key="rfi:GMP-170"
            ),
        )
    )
    (record,) = history["records"]
    (presence,) = record["series"]
    assert presence["presence"] == "not_observed_in_latest"
    assert presence["last_status"] is None
    compared = compare_payload(
        reads.compare(scene.principal, CompareRequest(series_id=_series_of(scene, "qxrfis")))
    )
    assert compared["comparable"] is True
    assert compared["not_observed"] == [{"identity_key": "rfi:GMP-170"}]
    assert "closed" not in compared
    assert {"identity_key": "rfi:GMP-170"} not in compared["changed"]
    added = {e["identity_key"] for e in compared["added"]}
    assert added == {
        "rfi:17",
        "rfi:174",
        "rfi:1740",
        "rfi:CD 50%-174",
        "rfi:GMP-175",
        "rfi:GMP-176",
    }
    changed = {e["identity_key"]: e for e in compared["changed"]}
    assert changed["rfi:GMP-174"]["changed_fields"] == ["rfi.ball_in_court"]
    assert all(e.get("new_status_class") != "closed" for e in compared["changed"])


def case_a_quarantined_latest_version_is_latest_unreadable(scene: ReadsScene) -> None:
    """Ruling R1-01: absence from an unreadable latest version is never inferred."""
    reads = service(scene)
    history = record_history_payload(
        reads.record_history(
            scene.principal,
            RecordHistoryRequest(
                project_id=RFI_PROJECT[1], record_family="rfis", identity_key="rfi:GMP-201"
            ),
        )
    )
    (record,) = history["records"]
    versions = {v["version"]: v for v in history["versions"]}
    (presence,) = record["series"]
    assert presence["presence"] == "latest_unreadable"
    assert presence["reasons"] == ["snapshot_quarantined"]
    # The history over the readable version still stands.
    (observation,) = record["observations"]
    assert presence["last_observed_version"] == observation["version"]
    readable = versions[observation["version"]]
    assert (readable["publication_date"], readable["derivation_state"]) == (
        "2026-11-01",
        "classified",
    )
    (latest,) = [v for v in versions.values() if v["is_latest"]]
    assert (latest["publication_date"], latest["derivation_state"]) == (
        "2026-11-15",
        "quarantined",
    )
    # The same series, read by `compare`: nothing is compared either.
    compared = compare_payload(
        reads.compare(scene.principal, CompareRequest(series_id=_series_of(scene, "qxrfiq")))
    )
    assert compared["comparable"] is False
    # A readable latest version keeps its presence and carries no reason.
    readable_history = record_history_payload(
        reads.record_history(
            scene.principal,
            RecordHistoryRequest(
                project_id=RFI_PROJECT[1], record_family="rfis", identity_key="rfi:GMP-170"
            ),
        )
    )
    (series,) = readable_history["records"][0]["series"]
    assert (series["presence"], series["reasons"]) == ("not_observed_in_latest", [])


def _assert_not_compared(compared: dict[str, Any], states: list[str]) -> None:
    """Ruling B2: a quarantined side is `comparable: false`, with nothing inferred."""
    assert compared["comparable"] is False
    assert [compared[section] for section in ("added", "not_observed", "changed", "lines")] == [
        [],
        [],
        [],
        [],
    ]
    assert compared["measures_delta"] == []
    assert [v["derivation_state"] for v in compared["versions"]] == states
    assert compared["next_cursor"] is None and compared["cursor_state"] is None


def case_a_quarantined_side_is_never_compared(scene: ReadsScene) -> None:
    """Ruling B2: either side quarantined answers `comparable: false` and nothing else."""
    reads = service(scene)
    series = _series_of(scene, "qxrfiq")
    to_quarantined = compare_payload(reads.compare(scene.principal, CompareRequest(series)))
    _assert_not_compared(to_quarantined, ["classified", "quarantined"])
    first, quarantined = (v["version"] for v in to_quarantined["versions"])
    # A later readable version: the quarantined one is now the `from` side.
    scene.ingest("rfis", "20261130-qxrfiq.csv", rfi_export(QUARANTINE_ROWS_LATER))
    from_quarantined = compare_payload(reads.compare(scene.principal, CompareRequest(series)))
    _assert_not_compared(from_quarantined, ["quarantined", "classified"])
    assert from_quarantined["versions"][0]["version"] == quarantined
    # The control: the two readable versions on either side of it compare.
    readable = compare_payload(
        reads.compare(scene.principal, CompareRequest(series, from_version=first))
    )
    assert readable["comparable"] is True
    assert readable["added"] == [{"identity_key": "rfi:GMP-203"}]
    assert readable["not_observed"] == []


def case_a_money_delta_across_two_currencies_is_currency_mixed(scene: ReadsScene) -> None:
    """Ruling R1-09: a delta whose two sides are in different currencies gives no value."""
    _reconciliation_project(scene, SOLO_PROJECT)
    reads = service(scene)
    data = _signature_bytes("reconciliation").replace(b"Synthetic line,$10", b"Synthetic void,$10")
    scene.ingest(SOLO_PROJECT[0], "20261119-qxsolo.csv", data)
    series = _series_of(scene, "qxsolo", SOLO_PROJECT[1])
    same = compare_payload(reads.compare(scene.principal, CompareRequest(series)))
    assert [v["currency"] for v in same["versions"]] == ["USD", "USD"]
    money = [d for d in same["measures_delta"] if d["measure"] == PRIME]
    assert money and all(d["state"] == "reportable" for d in money)
    assert {d["delta"]["currency"] for d in money} == {"USD"}
    # A correction of the binding's currency before the next version is derived.
    scene.correct(SOLO_PROJECT[0], currency="CAD")
    later = data.replace(b"Synthetic void,$10", b"Synthetic voided,$10")
    assert later != data
    scene.ingest(SOLO_PROJECT[0], "20261120-qxsolo.csv", later)
    mixed = compare_payload(reads.compare(scene.principal, CompareRequest(series)))
    assert [v["currency"] for v in mixed["versions"]] == ["USD", "CAD"]
    deltas = [d for d in mixed["measures_delta"] if d["measure"] in (PRIME, COMMITMENT)]
    assert len(deltas) == 8
    for delta in deltas:
        assert (delta["state"], delta["reasons"]) == ("not_reportable", ["currency_mixed"])
        assert "delta" not in delta


def case_an_unidentified_commitment_line_is_never_keyed(scene: ReadsScene) -> None:
    """Ruling R1-10: no shared empty key; the lines are counted and the total withheld."""
    reads = service(scene)
    name = "buyout_summary.commitment_line.amount"
    request = QueryRequest(
        project_id=PAIR_PROJECT[1], record_family="buyout", measures=(name,), include_rows=False
    )
    keyed = _measure(query_payload(reads.query(scene.principal, request)), name)
    assert keyed["unidentified_lines"] == 0
    assert keyed["total"] == {
        "state": "reportable",
        "value": {"amount": "1000.00", "currency": "USD"},
    }
    # Both commitment lines name one commitment (`SYN-0001.00001` is `SYN-0001.0001`).
    assert [k["value"]["amount"] for k in keyed["by_key"]] == ["1000.00"]
    # A later version whose second commitment line lost its number.
    data = _signature_bytes("buyout_summary")
    planted = data.replace(b",,,,SYN-0001.0001,Synthetic Vendor A,", b",,,,,Synthetic Vendor A,")
    assert planted != data
    scene.ingest(PAIR_PROJECT[0], "20261119-qxbuyout.csv", planted)
    unkeyed = _measure(query_payload(reads.query(scene.principal, request)), name)
    assert unkeyed["unidentified_lines"] == 1
    assert unkeyed["total"] == {"state": "not_reportable", "reasons": ["unidentified_key_present"]}
    (entry,) = unkeyed["by_key"]
    assert entry["key"] != [""] and entry["key"][0].startswith("commitment:")
    assert entry["value"] == {"amount": "600.00", "currency": "USD"}


def case_not_found_is_indistinguishable_for_foreign_and_unknown(scene: ReadsScene) -> None:
    reads = service(scene)
    foreign = _refusal(lambda: reads.query(OTHER_PRINCIPAL, _rfi_query(scene)))
    unknown = _refusal(
        lambda: reads.query(
            scene.principal, QueryRequest(project_id=UNKNOWN_PROJECT, record_family="rfis")
        )
    )
    assert foreign == unknown == (NotFoundError, (SafeDetail.PROJECT_ID,))
    series = _series_of(scene, "qxrfis")
    assert _refusal(lambda: reads.compare(OTHER_PRINCIPAL, CompareRequest(series_id=series))) == (
        _refusal(
            lambda: reads.compare(scene.principal, CompareRequest(series_id="prser_" + "0" * 32))
        )
    )
    assert _refusal(
        lambda: reads.catalog(OTHER_PRINCIPAL, CatalogRequest([RFI_PROJECT[1]]))
    ) == _refusal(lambda: reads.catalog(scene.principal, CatalogRequest([UNKNOWN_PROJECT])))
    record_id = record_history_payload(
        reads.record_history(
            scene.principal,
            RecordHistoryRequest(
                project_id=RFI_PROJECT[1], record_family="rfis", identity_key="rfi:GMP-174"
            ),
        )
    )["records"][0]["record_id"]
    unknown_record = "prrec_" + "synunknownrec01"
    foreign_answer = record_history_payload(
        reads.record_history(OTHER_PRINCIPAL, RecordHistoryRequest(record_ids=[record_id]))
    )
    unknown_answer = record_history_payload(
        reads.record_history(scene.principal, RecordHistoryRequest(record_ids=[unknown_record]))
    )
    assert foreign_answer["records"] == unknown_answer["records"] == []
    assert foreign_answer["not_found"] == [record_id]
    assert unknown_answer["not_found"] == [unknown_record]


def case_the_facade_answers_absent_unbound_and_quarantined_projects(scene: ReadsScene) -> None:
    reads = service(scene)
    state = {
        key: (a.state, a.reason)
        for key, a in (
            ("rfis", reads.availability(scene.principal, RFI_PROJECT[1])),
            ("absent", reads.availability(scene.principal, UNKNOWN_PROJECT)),
            ("foreign", reads.availability(OTHER_PRINCIPAL, RFI_PROJECT[1])),
            ("never", reads.availability(scene.principal, NEVER_PROJECT[1])),
            ("quarantined", reads.availability(scene.principal, QUARANTINED_PROJECT[1])),
        )
    }
    assert state == {
        "rfis": ("available", None),
        "absent": ("unavailable", "unbound"),
        "foreign": ("unavailable", "unbound"),
        "never": ("unavailable", "never_ingested"),
        "quarantined": ("unavailable", "all_quarantined"),
    }
    off = service(scene, reads_enabled=False)
    assert off.availability(scene.principal, RFI_PROJECT[1]).reason == "reads_disabled"
    assert off.match_rfis(scene.principal, RFI_PROJECT[1], [(None, 174)]) == ()
    summary = project_summary_payload(reads.project_summary(scene.principal, RFI_PROJECT[1]))
    counts = {c["series_id"]: c for c in summary["counts"]}
    assert len(counts) == 4
    outstanding = counts[_series_of(scene, "qxrfis")]
    assert outstanding["measure"] == "open_outstanding.record_count"
    assert outstanding["total"] == {"state": "reportable", "value": "7"}
    assert outstanding["qualifiers"] == []
    assert counts[_series_of(scene, "qxrfilinks")]["total"] == {"state": "reportable", "value": "1"}
    quarantined = [c for c in summary["counts"] if c["total"]["state"] == "not_reportable"]
    assert quarantined and all("snapshot_quarantined" in c["total"]["reasons"] for c in quarantined)
    absent = project_summary_payload(reads.project_summary(scene.principal, UNKNOWN_PROJECT))
    assert absent["counts"] == [] and absent["availability"] == {
        "state": "unavailable",
        "reason": "unbound",
    }
    matched = {
        (m.prefix, m.suffix): (m.state, sorted(c[0] or "" for c in m.candidates))
        for m in reads.match_rfis(
            scene.principal, RFI_PROJECT[1], [(None, 174), ("GMP", 174), (None, 1741), (None, 175)]
        )
    }
    assert matched == {
        (None, 174): ("ambiguous_prefix", ["", "CD 50%", "GMP"]),
        ("GMP", 174): ("exact", ["GMP"]),
        (None, 1741): ("none", []),
        (None, 175): ("exact", ["GMP"]),
    }


#: Every Project of the world with the RFI numbers a batch asks for it (WP5 ruling D7).
_BATCH: Final = (
    (RFI_PROJECT[1], ((None, 174), ("GMP", 174), (None, 1741), (None, 175), (None, 0))),
    (OBS_PROJECT[1], ((None, 174),)),
    (NOTE_PROJECT[1], ()),
    (PAIR_PROJECT[1], ((None, 175), ("GMP", 201))),
    (QUARANTINED_PROJECT[1], ((None, 201), (None, 203))),
    (NEVER_PROJECT[1], ((None, 174),)),
    (UNKNOWN_PROJECT, ((None, 174),)),
)


def case_the_batched_facade_answers_as_the_per_project_methods(scene: ReadsScene) -> None:
    """WP5 D7: `context_summaries` is, per request, `availability`, `project_summary`, `match_rfis`.

    The whole world in one batch, every Project alone, every adjacent pair, a
    Project asked twice with other numbers, for the Principal and for another
    one; then the switch off and the bounds.
    """
    reads = service(scene)
    batches: list[list[tuple[str, tuple[tuple[str | None, int], ...]]]] = [list(_BATCH)]
    batches += [[request] for request in _BATCH]
    batches += [list(pair) for pair in itertools.pairwise(_BATCH)]
    batches.append([_BATCH[0], _BATCH[1], (RFI_PROJECT[1], ((None, 201), (None, 174))), _BATCH[0]])
    for principal in (scene.principal, OTHER_PRINCIPAL):
        for batch in batches:
            answered = reads.context_summaries(principal, batch)
            assert len(answered) == len(batch)
            for one, (project_id, numbers) in zip(answered, batch, strict=True):
                assert one.project_id == project_id
                assert one.availability == reads.availability(principal, project_id)
                summary = reads.project_summary(principal, project_id)
                assert one.summary == summary
                assert project_summary_payload(one.summary) == project_summary_payload(summary)
                assert one.rfis == reads.match_rfis(principal, project_id, numbers)
    # The world is varied enough to mean something.
    whole = reads.context_summaries(scene.principal, _BATCH)
    assert {a.project_id: a.availability.reason for a in whole} == {
        RFI_PROJECT[1]: None,
        OBS_PROJECT[1]: None,
        NOTE_PROJECT[1]: "all_quarantined",
        PAIR_PROJECT[1]: None,
        QUARANTINED_PROJECT[1]: "all_quarantined",
        NEVER_PROJECT[1]: "never_ingested",
        UNKNOWN_PROJECT: "unbound",
    }
    assert {m.state for m in whole[0].rfis} == {"exact", "ambiguous_prefix", "none"}
    assert whole[0].summary.counts and whole[1].summary.counts
    disabled = service(scene, reads_enabled=False)
    off = disabled.context_summaries(scene.principal, _BATCH)
    for one, (project_id, _numbers) in zip(off, _BATCH, strict=True):
        assert one.availability == disabled.availability(scene.principal, project_id)
        assert one.summary == disabled.project_summary(scene.principal, project_id)
        assert one.rfis == ()
    assert reads.context_summaries(scene.principal, ()) == ()
    with pytest.raises(InvalidRequestError) as raised:
        reads.context_summaries(scene.principal, [(RFI_PROJECT[1], [(None, n) for n in range(11)])])
    assert raised.value.safe_details == (SafeDetail.IDENTIFIERS,)
    with pytest.raises(InvalidRequestError) as raised:
        reads.context_summaries(scene.principal, [(RFI_PROJECT[1], ())] * 51)
    assert raised.value.safe_details == (SafeDetail.PROJECT_IDS,)


def case_coverage_carries_per_version_filter_semantics(scene: ReadsScene) -> None:
    payload = coverage_payload(
        service(scene).coverage(
            scene.principal, CoverageRequest([RFI_PROJECT[1]], record_family="rfis")
        )
    )
    (project,) = payload["projects"]
    (source,) = project["sources"]
    series = {s["series_id"]: s for s in source["series"]}
    rfis = series[_series_of(scene, "qxrfis")]
    # Declared after the later-label version was first seen, before the earlier one.
    assert [v["filter_semantics"] for v in rfis["version_filter_semantics"]] == [
        "operator_declared",
        "unknown",
    ]
    assert rfis["filter_semantics"] == "unknown"
    assert project["retired_sources"] == []
    assert _refusal(
        lambda: service(scene).coverage(scene.principal, CoverageRequest([UNKNOWN_PROJECT]))
    ) == (NotFoundError, (SafeDetail.PROJECT_IDS,))


def case_rows_carry_typed_fields_and_raw_text(scene: ReadsScene) -> None:
    payload = query_payload(
        service(scene).query(
            scene.principal,
            _rfi_query(
                scene,
                series_id=_series_of(scene, "qxrfis"),
                identifiers=[IdentifierItem("rfi", "174")],
            ),
        )
    )
    rows = payload["rows"]
    assert isinstance(rows, list)
    assert sorted(r["fields"]["rfi.number"] for r in rows) == ["174", "CD 50%-174", "GMP-174"]
    gmp = next(r for r in rows if r["fields"]["rfi.number"] == "GMP-174")
    assert gmp["fields"]["rfi.date_initiated"] == "2026-11-01"
    assert gmp["raw"]["rfi.date_initiated"] == "11/1/2026"
    assert "rfi.subject" not in gmp["raw"]
    assert gmp["fields"]["rfi.due_date_variance_days"] == "3"
    (match,) = payload["rfi_match"]
    assert match["state"] == "ambiguous_prefix"


def case_filtered_measures_sum_only_the_selected_lines(scene: ReadsScene) -> None:
    """Ruling B1 (amended): the filters select the lines measured, the version is the same."""
    _reconciliation_project(scene, SOLO_PROJECT)
    reads = service(scene)
    whole = query_payload(reads.query(scene.principal, _reconciliation_query(SOLO_PROJECT)))
    filtered = query_payload(
        reads.query(scene.principal, _reconciliation_query(SOLO_PROJECT, **_FROM_JUNE_2))
    )
    assert _measure(whole, PRIME)["version"] == _measure(filtered, PRIME)["version"]
    assert _amounts(whole, PRIME) == {
        "approved": "300.00",
        "pending": "40.00",
        "void": "10.00",
        "unknown": "0.00",
    }
    # PCO 3 (void, 6/2) and PCO 4 (approved, 6/3) only.
    assert _amounts(filtered, PRIME) == {
        "approved": "200.00",
        "pending": "0.00",
        "void": "10.00",
        "unknown": "0.00",
    }
    # No commitment line is selected, yet the column is populated in the version:
    # an exact zero, never `source_column_unpopulated` (judged over the version).
    assert _amounts(filtered, COMMITMENT) == {
        "approved": "0.00",
        "pending": "0.00",
        "void": "0.00",
        "unknown": "0.00",
    }
    pending = query_payload(
        reads.query(
            scene.principal, _reconciliation_query(SOLO_PROJECT, status_classes=["pending"])
        )
    )
    assert _amounts(pending, PRIME)["pending"] == "40.00"
    assert _amounts(pending, PRIME)["approved"] == "0.00"
    series = _series_of(scene, "qxrfis")
    counts = ("open_outstanding.record_count",)
    rfis = [
        query_payload(
            reads.query(
                scene.principal,
                _rfi_query(scene, series_id=series, measures=counts, include_rows=False, **extra),
            )
        )
        for extra in ({}, {"identifiers": [IdentifierItem("rfi", "174")]})
    ]
    assert [_measure(p, counts[0])["total"] for p in rfis] == [
        {"state": "reportable", "value": "7"},
        {"state": "reportable", "value": "3"},
    ]


def case_measure_scope_is_version_only_without_a_row_filter(scene: ReadsScene) -> None:
    _reconciliation_project(scene, SOLO_PROJECT)
    reads = service(scene)
    variants: list[tuple[dict[str, Any], str]] = [
        ({}, "version"),
        # A date field without a bound selects every line.
        ({"date_field": "pco.date_created"}, "version"),
        ({"status_classes": ["approved"]}, "filtered"),
        ({"statuses": ["Void"]}, "filtered"),
        (_FROM_JUNE_2, "filtered"),
        ({"date_field": "pco.date_created", "date_to": date(2026, 6, 1)}, "filtered"),
        ({"identifiers": [IdentifierItem("pco", "4")]}, "filtered"),
        ({"group_keys": ["SYN-CO-1"]}, "filtered"),
        ({"text": "synthetic"}, "filtered"),
    ]
    for fields, expected in variants:
        payload = query_payload(
            reads.query(scene.principal, _reconciliation_query(SOLO_PROJECT, **fields))
        )
        scopes = {m["measure_scope"] for m in payload["measures"]}
        assert scopes == {expected}, (fields, scopes)
    summary = project_summary_payload(reads.project_summary(scene.principal, RFI_PROJECT[1]))
    assert {c["measure_scope"] for c in summary["counts"]} == {"version"}


def case_a_mismatched_version_blocks_money_under_either_scope(scene: ReadsScene) -> None:
    """D9 under ruling B1 (amended): the version's mismatch blocks a filtered sum too."""
    _reconciliation_project(scene, MISMATCH_PROJECT)
    reads = service(scene)
    blocked = {
        status: ["reconciliation_mismatch"] for status in ("approved", "pending", "void", "unknown")
    }
    for fields in ({}, _FROM_JUNE_2, {"statuses": ["Approved"]}, {"text": "commitment"}):
        payload = query_payload(
            reads.query(scene.principal, _reconciliation_query(MISMATCH_PROJECT, **fields))
        )
        assert _measure(payload, PRIME)["measure_scope"] == ("filtered" if fields else "version")
        assert _amounts(payload, PRIME) == blocked, fields
        assert _amounts(payload, COMMITMENT) == blocked, fields


def case_a_filtered_answer_never_claims_its_sum_matches_a_stated_total(
    scene: ReadsScene,
) -> None:
    """The stated totals judge the whole version; none is set against the filtered sum."""
    _reconciliation_project(scene, SOLO_PROJECT)
    reads = service(scene)
    whole = query_payload(reads.query(scene.principal, _reconciliation_query(SOLO_PROJECT)))
    filtered = query_payload(
        reads.query(scene.principal, _reconciliation_query(SOLO_PROJECT, **_FROM_JUNE_2))
    )
    totals = filtered["source_totals"]
    assert totals["reconciliation_scope"] == "version"
    # The same evidence in both scopes: each outcome is against the version's lines.
    assert totals == whole["source_totals"]
    (grand,) = [
        e
        for e in totals["entries"]
        if e["scope"] == "grand" and e["field_key"] == "prime_co_line.amount"
    ]
    assert (grand["value"], grand["computed_value"], grand["outcome"]) == (
        "350.00",
        "350.00",
        "match",
    )
    sums = _amounts(filtered, PRIME)
    assert sums["approved"] == "200.00" and sums["void"] == "10.00"
    for measure in filtered["measures"]:
        assert measure["measure_scope"] == "filtered"
        assert not set(measure) & {"outcome", "computed_value", "reconciliation", "stated"}
        assert measure["qualifiers"] == []


def case_measures_are_identical_across_pages_of_one_query(scene: ReadsScene) -> None:
    """Measures are per answer scope, never per page (ruling B1, amended)."""
    _reconciliation_project(scene, SOLO_PROJECT)
    reads = service(scene)
    for fields in ({}, {"text": "synthetic"}):
        cursor: str | None = None
        pages: list[dict[str, Any]] = []
        for _page in range(10):
            pages.append(
                query_payload(
                    reads.query(
                        scene.principal,
                        _reconciliation_query(SOLO_PROJECT, limit=1, cursor=cursor, **fields),
                    )
                )
            )
            cursor = pages[-1]["next_cursor"]
            if cursor is None:
                break
        assert len(pages) >= 3, fields
        assert sum(len(p["rows"]) for p in pages) == len(pages)
        assert all(p["measures"] == pages[0]["measures"] for p in pages), fields
        alone = query_payload(
            reads.query(
                scene.principal,
                _reconciliation_query(SOLO_PROJECT, include_rows=False, **fields),
            )
        )
        assert alone["measures"] == pages[0]["measures"], fields
    assert _amounts(pages[0], PRIME)["pending"] == "0.00"  # PCO 2 has no description


CASES: Final = (
    case_catalog_lists_series_with_their_latest_version,
    case_query_pages_are_disjoint_and_complete,
    case_a_new_version_between_pages_restarts,
    case_a_cursor_of_another_request_or_principal_is_a_conflict,
    case_source_totals_are_never_measures,
    case_a_cross_check_mismatch_withholds_both_columns,
    case_a_stale_cross_check_is_ignored_after_a_rederivation,
    case_record_history_spans_three_rfi_views,
    case_changed_fields_compare_consecutive_versions_only,
    case_changed_since_names_the_readable_baseline_across_a_gap,
    case_an_absent_record_is_not_observed_never_closed,
    case_a_quarantined_latest_version_is_latest_unreadable,
    case_a_quarantined_side_is_never_compared,
    case_a_money_delta_across_two_currencies_is_currency_mixed,
    case_an_unidentified_commitment_line_is_never_keyed,
    case_not_found_is_indistinguishable_for_foreign_and_unknown,
    case_the_facade_answers_absent_unbound_and_quarantined_projects,
    case_the_batched_facade_answers_as_the_per_project_methods,
    case_coverage_carries_per_version_filter_semantics,
    case_rows_carry_typed_fields_and_raw_text,
    case_filtered_measures_sum_only_the_selected_lines,
    case_measure_scope_is_version_only_without_a_row_filter,
    case_a_mismatched_version_blocks_money_under_either_scope,
    case_a_filtered_answer_never_claims_its_sum_matches_a_stated_total,
    case_measures_are_identical_across_pages_of_one_query,
)

__all__ = ["CASES", "extend_world", "service"]
