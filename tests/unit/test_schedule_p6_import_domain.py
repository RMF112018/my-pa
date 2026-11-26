"""P6 XER S7-3: the pure admission and matching decisions (FAST).

Schedule XER import contract sections 9.1 (sniff, snapshot), 10.3 (strict
inputs), 11.1 (Series identity) and 11.3 (activity matching). Synthetic
values only.
"""

from __future__ import annotations

import hashlib
from typing import Final

import pytest

from my_pa.domain.schedule.p6_import import (
    P6_IMPORT_FIELDS,
    P6ActivityIdentity,
    P6ProjectIdentity,
    P6RenumberCandidate,
    P6RequestError,
    P6Snapshot,
    P6SourceFormat,
    match_p6_activities,
    p6_identity_changed,
    p6_import_request,
    p6_import_request_digest,
    sniff_p6_format,
)
from tests.fixtures import schedule_p6_xer as xer

P: Final = "prn_sp6unit0001"
VERSION: Final = "fv1_" + "a" * 64
SHA: Final = "b" * 64


def _payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "project_id": "prj_sp6unit0001",
        "series_name": "Master  Schedule ",
        "workspace_id": "syn",
        "path": "exports/schedule.xer",
        "expected_version": VERSION,
        "expected_sha256": SHA,
        "format": "p6_xer",
        "idempotency_key": "p6-unit-0001",
    }
    payload.update(changes)
    return {key: value for key, value in payload.items() if value is not None}


def test_a_well_formed_request_is_admitted() -> None:
    request = p6_import_request(_payload())
    assert request.series_name is not None and request.series_name.name == "Master Schedule"
    assert request.format is P6SourceFormat.P6_XER
    assert request.accept_project_identity_change is False
    assert request.series_name_if_new is None


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"role": "baseline"}, "role"),
        ({"workspace_id": None}, "workspace_id"),
        ({"expected_version": "fv0_abc"}, "expected_version"),
        ({"expected_sha256": SHA.upper()}, "expected_sha256"),
        ({"format": "pdf"}, "format"),
        ({"path": "/etc/passwd"}, "path"),
        ({"path": "exports/"}, "path"),
        ({"workspace_id": "Syn"}, "workspace_id"),
        ({"series_auto": "yes"}, "series_auto"),
        ({"accept_project_identity_change": 1}, "accept_project_identity_change"),
        ({"series_id": "sser_sp6unit0001aaaa"}, "series_id"),
        ({"series_name": None}, "series_id"),
        ({"project_id": "notanid"}, "project_id"),
        ({"idempotency_key": "short"}, "idempotency_key"),
        ({"series_name": "\u0000"}, "series_name"),
    ],
)
def test_inputs_are_strict(changes: dict[str, object], field: str) -> None:
    with pytest.raises(P6RequestError) as raised:
        p6_import_request(_payload(**changes))
    assert raised.value.field == field
    assert str(raised.value) == field


def test_the_admitted_keys_are_exactly_section_10_3() -> None:
    assert (
        frozenset(
            {
                "project_id",
                "series_id",
                "series_name",
                "series_auto",
                "workspace_id",
                "path",
                "expected_version",
                "expected_sha256",
                "format",
                "accept_project_identity_change",
                "supersedes_publication_id",
                "idempotency_key",
            }
        )
        == P6_IMPORT_FIELDS
    )


def test_the_digest_ignores_the_key_and_name_spacing_but_not_the_bytes() -> None:
    one = p6_import_request(_payload())
    same = p6_import_request(
        _payload(idempotency_key="p6-unit-0002", series_name="master schedule")
    )
    other = p6_import_request(_payload(expected_sha256="c" * 64))
    moved = p6_import_request(_payload(expected_version="fv1_" + "d" * 64))
    digest = p6_import_request_digest(P, one)
    assert digest == p6_import_request_digest(P, same)
    assert digest != p6_import_request_digest(P, other)
    assert digest != p6_import_request_digest(P, moved)
    assert digest != p6_import_request_digest("prn_sp6unit0002", one)


@pytest.mark.parametrize("name", sorted(xer.CASES))
def test_every_fixture_with_its_header_and_end_sniffs_as_xer(name: str) -> None:
    data = xer.build(name).data
    expected = (
        P6SourceFormat.P6_XER
        if data.startswith(b"ERMHDR\t") and data.rstrip(b"\r\n\t ").endswith(b"\n%E")
        else None
    )
    assert sniff_p6_format(data) is expected


def test_the_sniff_reads_bytes_only() -> None:
    xer_bytes = xer.build("full_valid").data
    assert sniff_p6_format(xer_bytes) is P6SourceFormat.P6_XER
    assert sniff_p6_format(xer_bytes + b"\r\n\r\n") is P6SourceFormat.P6_XER
    assert sniff_p6_format(b"%PDF-1.7\n%%EOF\n") is None
    assert sniff_p6_format(xer_bytes.replace(b"%E\r\n", b"")) is None
    assert sniff_p6_format(xer_bytes + b"%R\textra\r\n") is None
    assert sniff_p6_format(b"\xef\xbb\xbf" + xer_bytes) is None
    assert sniff_p6_format(b"ERMHDR 26.4\n%E\n") is None


def test_a_snapshot_is_its_bytes() -> None:
    snapshot = P6Snapshot(b"ERMHDR\t26.4\n%E\n", P6SourceFormat.P6_XER)
    assert snapshot.sha256 == hashlib.sha256(b"ERMHDR\t26.4\n%E\n").hexdigest()
    assert snapshot.size_bytes == 15
    with pytest.raises(ValueError, match="1 to 16777216"):
        P6Snapshot(b"", P6SourceFormat.P6_XER)
    with pytest.raises(ValueError, match="1 to 16777216"):
        P6Snapshot(b"x" * (16_777_216 + 1), P6SourceFormat.P6_XER)


def test_identity_is_changed_only_when_nothing_is_shared() -> None:
    current = P6ProjectIdentity("SYN-PRJ", "guid-a")
    assert not p6_identity_changed(current, [], accepted=False)
    assert not p6_identity_changed(
        current, [P6ProjectIdentity("SYN-PRJ", "guid-b")], accepted=False
    )
    assert not p6_identity_changed(
        current, [P6ProjectIdentity("SYN-OLD", "guid-a")], accepted=False
    )
    assert p6_identity_changed(current, [P6ProjectIdentity("SYN-OLD", "guid-b")], accepted=False)
    assert not p6_identity_changed(current, [P6ProjectIdentity("SYN-OLD", "guid-b")], accepted=True)
    assert p6_identity_changed(
        P6ProjectIdentity(None, None), [P6ProjectIdentity(None, None)], accepted=False
    )


def test_matching_is_exact_and_renumbering_is_only_a_hint() -> None:
    before = [
        P6ActivityIdentity("SYN-1000", "g1"),
        P6ActivityIdentity("SYN-1010", "g2"),
        P6ActivityIdentity("SYN-1020", "g3"),
        P6ActivityIdentity("SYN-1030", None),
    ]
    after = [
        P6ActivityIdentity("SYN-1000", "g1"),
        P6ActivityIdentity("SYN-1011", "g2"),
        P6ActivityIdentity("SYN-1040", None),
        P6ActivityIdentity("SYN-1050", "g9"),
    ]
    matching = match_p6_activities(before, after)
    assert matching.removed == ("SYN-1010", "SYN-1020", "SYN-1030")
    assert matching.added == ("SYN-1011", "SYN-1040", "SYN-1050")
    assert matching.renumber_candidates == (P6RenumberCandidate("SYN-1010", "SYN-1011"),)


def test_a_guid_shared_by_two_added_activities_names_no_candidate() -> None:
    before = [P6ActivityIdentity("SYN-1010", "g2")]
    after = [P6ActivityIdentity("SYN-1011", "g2"), P6ActivityIdentity("SYN-1012", "g2")]
    assert match_p6_activities(before, after).renumber_candidates == ()
