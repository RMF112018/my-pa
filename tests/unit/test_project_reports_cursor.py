"""WP4P-S1: the project-reports cursor (design 2.8; ruling D4 (b)).

Encode, decode, malformed and oversize tokens; the scope digest binds the
resolved version set, so a new version, a re-derivation or a binding
correction restarts the cursor; and the envelope equals the communications
cursor's (the slices may not import each other, but a test may import both).
Every value is synthetic.
"""

from __future__ import annotations

import base64
import json

import pytest

from my_pa.domain.communications import cursor as communications
from my_pa.domain.project_reports.cursor import (
    CURSOR_VERSION,
    MAX_CURSOR_CHARACTERS,
    PROJECT_REPORTS_READ_GENERATION,
    PROJECT_REPORTS_READS,
    ComparePosition,
    CursorMalformedError,
    ProjectReportsCursor,
    QueryPosition,
    ResolvedVersion,
    compare_position,
    cursor_binding,
    decode_cursor,
    encode_cursor,
    grant_digest,
    query_position,
    scope_digest,
)

SERIES = "prser_" + "a" * 32
VERSION = "isnp_synthetic0001"
DERIVATION = "prdrv_synthetic0001"
RESOLVED = (ResolvedVersion(SERIES, VERSION, DERIVATION),)


def _cursor(position: QueryPosition | ComparePosition) -> ProjectReportsCursor:
    binding = cursor_binding(
        capability="project_reports.query",
        principal_id="prn_synthetic0001",
        request={"project_id": "prj_synthetic0001", "record_family": "rfis"},
    )
    return ProjectReportsCursor(binding, scope_digest(None, RESOLVED), position)


def _raw(document: object) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def test_a_query_and_a_compare_cursor_round_trip() -> None:
    query = _cursor(QueryPosition(2, VERSION, 17))
    assert decode_cursor(encode_cursor(query), query_position) == query
    compare = _cursor(ComparePosition(3, "a" * 64))
    assert decode_cursor(encode_cursor(compare), compare_position) == compare


@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        "not base64!",
        "a" * (MAX_CURSOR_CHARACTERS + 1),
        _raw([1]),
        _raw({"v": 1, "b": "a" * 64, "s": "a" * 64}),
        _raw({"v": 2, "b": "a" * 64, "s": "a" * 64, "p": [0, VERSION, 1]}),
        _raw({"v": True, "b": "a" * 64, "s": "a" * 64, "p": [0, VERSION, 1]}),
        _raw({"v": 1, "b": "A" * 64, "s": "a" * 64, "p": [0, VERSION, 1]}),
        _raw({"v": 1, "b": "a" * 64, "s": "a" * 63, "p": [0, VERSION, 1]}),
        _raw({"v": 1, "b": "a" * 64, "s": "a" * 64, "p": [0, VERSION]}),
        _raw({"v": 1, "b": "a" * 64, "s": "a" * 64, "p": [-1, VERSION, 1]}),
        _raw({"v": 1, "b": "a" * 64, "s": "a" * 64, "p": [0, "prdrv_synthetic1", 1]}),
        _raw({"v": 1, "b": "a" * 64, "s": "a" * 64, "p": [0, VERSION, 0]}),
        _raw({"v": 1, "b": "a" * 64, "s": "a" * 64, "p": [0, VERSION, True]}),
    ],
)
def test_a_malformed_query_cursor_is_refused(token: object) -> None:
    with pytest.raises(CursorMalformedError):
        decode_cursor(token, query_position)


@pytest.mark.parametrize("position", [[4, "a"], [0, ""], [0, "\n"], [0, 5], "x"])
def test_a_malformed_compare_position_is_refused(position: object) -> None:
    token = _raw({"v": 1, "b": "a" * 64, "s": "a" * 64, "p": position})
    with pytest.raises(CursorMalformedError):
        decode_cursor(token, compare_position)


def test_an_oversize_cursor_is_never_written() -> None:
    with pytest.raises(ValueError, match="2048"):
        encode_cursor(_cursor(ComparePosition(0, "k" * 1600)))


def _binding(
    capability: str = "project_reports.query",
    principal_id: str = "prn_synthetic0001",
    project_id: str = "prj_synthetic0001",
) -> str:
    return cursor_binding(
        capability=capability, principal_id=principal_id, request={"project_id": project_id}
    )


def test_the_binding_names_the_request_principal_and_capability() -> None:
    first = _binding()
    assert first == _binding()
    assert first != _binding(principal_id="prn_synthetic0002")
    assert first != _binding(capability="project_reports.compare")
    assert first != _binding(project_id="prj_synthetic0002")


def test_a_changed_version_set_restarts_the_cursor() -> None:
    """Ruling D4 (b): a new version, a re-derivation or a rebind changes `s`."""
    first = scope_digest(None, RESOLVED)
    assert first == scope_digest(None, [*RESOLVED, *RESOLVED])
    other = ResolvedVersion(SERIES, "isnp_synthetic0002", "prdrv_synthetic0002")
    assert scope_digest(None, [*RESOLVED, other]) == scope_digest(None, [other, *RESOLVED])
    assert scope_digest(None, [*RESOLVED, other]) != first  # a new version arrived
    rederived = ResolvedVersion(SERIES, VERSION, "prdrv_synthetic0009")
    assert scope_digest(None, [rederived]) != first  # the same version, re-derived
    assert scope_digest(None, RESOLVED, generation=2) != first
    granted = grant_digest([("project_reports.query", "project_reports_read")])
    assert scope_digest(granted, RESOLVED) != first


def test_the_grant_digest_reads_only_the_project_reports_names() -> None:
    assert grant_digest(None) is None
    mine = [("project_reports.query", "project_reports_read"), ("project_reports.catalog", None)]
    assert grant_digest(mine) == grant_digest([*reversed(mine), ("tasks.list", "x")])
    assert grant_digest(mine) != grant_digest(mine[:1])
    assert len(PROJECT_REPORTS_READS) == 5
    assert all(name.startswith("project_reports.") for name in PROJECT_REPORTS_READS)
    assert PROJECT_REPORTS_READ_GENERATION == 1


def test_the_envelope_equals_the_communications_cursor() -> None:
    """Same version, bound, keys and canonical base64url; each decodes the other's envelope."""
    assert CURSOR_VERSION == communications.CURSOR_VERSION
    assert MAX_CURSOR_CHARACTERS == communications.MAX_CURSOR_CHARACTERS
    ours = _cursor(QueryPosition(0, VERSION, 1))
    token = encode_cursor(ours)
    padded = token + "=" * (-len(token) % 4)
    document = json.loads(base64.urlsafe_b64decode(padded))
    assert set(document) == {"v", "b", "s", "p"}
    assert token == _raw(document)  # canonical: sorted keys, no whitespace, unpadded
    thread = communications.ThreadPosition(
        communications.parse_instant_token("2026-11-24T12:00:00.000000Z"), "cmsg_synthetic01"
    )
    decoded = communications.decode_cursor(token, lambda _p: thread)
    assert (decoded.binding, decoded.scope) == (ours.binding, ours.scope)
    theirs = communications.encode_cursor(
        communications.CommunicationsCursor("b" * 64, "c" * 64, thread)
    )
    back = decode_cursor(theirs, lambda _p: QueryPosition(0, VERSION, 1))
    assert (back.binding, back.scope) == ("b" * 64, "c" * 64)
