"""Project reports: header signature, filename labels and version comparison.

Plan 4.1/4.2 (signature), 6.2 (series and versions) and 6.3 (closure is never
inferred from disappearance; PULSE-AC-10, AC-11). Synthetic names and ids only.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from my_pa.domain.project_reports.labels import (
    FilenameLabels,
    SeriesKey,
    filename_labels,
    series_key,
)
from my_pa.domain.project_reports.model import RejectionCode, StatusClass, VersionPresence
from my_pa.domain.project_reports.signature import (
    SIGNATURE_VERSION,
    header_refusal,
    header_signature,
)
from my_pa.domain.project_reports.versions import (
    RecordObservation,
    VersionRef,
    compare_versions,
    latest_version,
)


def test_the_signature_is_the_compact_json_digest() -> None:
    cells = ["Col A", "Spalte ü", "C"]
    expected = hashlib.sha256('["Col A","Spalte ü","C"]'.encode()).hexdigest()
    assert header_signature(cells) == expected
    assert SIGNATURE_VERSION == "pulse_header_signature_v1"


def test_any_header_change_is_a_new_signature() -> None:
    base = header_signature(["A", "B", "C"])
    assert header_signature(["B", "A", "C"]) != base
    assert header_signature(["A", "B", "C "]) != base
    assert header_signature(["a", "B", "C"]) != base
    assert header_signature(["A", "B"]) != base
    assert header_signature(("A", "B", "C")) == base


def test_the_signature_takes_text_cells_only() -> None:
    with pytest.raises(TypeError):
        header_signature("ABC")
    with pytest.raises(TypeError):
        header_signature(["A", 1])  # type: ignore[list-item]


def test_header_refusals() -> None:
    assert header_refusal(["A", "B"]) is None
    assert header_refusal([]) is RejectionCode.INVALID_HEADER
    assert header_refusal(["A", ""]) is RejectionCode.INVALID_HEADER
    assert header_refusal(["A", "A"]) is RejectionCode.INVALID_HEADER


@pytest.mark.parametrize(
    ("name", "labels"),
    [
        ("20300102-open-items.csv", FilenameLabels("20300102", "open-items")),
        ("dir/sub/20300102-a.csv", FilenameLabels("20300102", "a")),
        ("20300102-recently-closed.csv", FilenameLabels("20300102", "recently-closed")),
        ("20301302-a.csv", FilenameLabels(None, None)),  # not a calendar date
        ("2030010-a.csv", FilenameLabels(None, None)),
        ("20300102-.csv", FilenameLabels(None, None)),
        ("20300102-a.CSV", FilenameLabels(None, None)),
        ("open-items.csv", FilenameLabels(None, None)),
    ],
)
def test_filename_labels(name: str, labels: FilenameLabels) -> None:
    assert filename_labels(name) == labels


def test_two_slugs_sharing_a_signature_are_two_series() -> None:
    one = series_key("src_SYNTH0001", "d/20300102-view-one.csv", "f" * 64)
    two = series_key("src_SYNTH0001", "d/20300102-view-two.csv", "f" * 64)
    assert one != two
    assert one == SeriesKey("src_SYNTH0001", "view-one", "f" * 64)
    # A new date prefix with the same slug and signature is the same series.
    assert series_key("src_SYNTH0001", "d/20300109-view-one.csv", "f" * 64) == one


def _at(day: int) -> datetime:
    return datetime(2030, 1, day, tzinfo=UTC)


V1 = VersionRef("snp_SYNTH0001", "20300101", _at(5))
V2 = VersionRef("snp_SYNTH0002", "20300108", _at(2))  # later label, earlier arrival
UNLABELLED = VersionRef("snp_SYNTH0003", None, _at(9))


def test_latest_is_a_total_order_never_arrival() -> None:
    assert latest_version([V2, V1]) == V2
    assert latest_version([V1, V2, UNLABELLED]) == V2
    assert latest_version([]) is None
    tie_a = VersionRef("snp_SYNTHaaaa", "20300101", _at(1))
    tie_b = VersionRef("snp_SYNTHbbbb", "20300101", _at(1))
    assert latest_version([tie_b, tie_a]) == latest_version([tie_a, tie_b]) == tie_b


def test_a_record_absent_from_the_latest_version_is_not_observed_never_closed() -> None:
    observations = [
        RecordObservation(V1, "rfi:1", StatusClass.OPEN),
        RecordObservation(V1, "rfi:2", StatusClass.OPEN),
        RecordObservation(V2, "rfi:2", StatusClass.CLOSED),
        RecordObservation(V2, "rfi:3", StatusClass.OPEN),
    ]
    presence = compare_versions([V1, V2], reversed(observations))
    assert presence["rfi:1"].presence is VersionPresence.NOT_OBSERVED_IN_LATEST
    # Its status stays as last observed, with the version that observed it.
    assert presence["rfi:1"].last_status is StatusClass.OPEN
    assert presence["rfi:1"].last_observed == V1
    assert presence["rfi:2"].presence is VersionPresence.OBSERVED_IN_LATEST
    assert presence["rfi:2"].last_status is StatusClass.CLOSED  # from a later status column
    assert presence["rfi:3"].presence is VersionPresence.OBSERVED_IN_LATEST
    assert {p.presence.value for p in presence.values()} <= {
        "observed_in_latest",
        "not_observed_in_latest",
    }


def test_an_observation_outside_the_series_is_refused() -> None:
    with pytest.raises(ValueError, match="outside"):
        compare_versions([V1], [RecordObservation(V2, "rfi:1")])
