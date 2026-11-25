"""P6 XER S7-3: the parent decodes the child's frame without the parser (FAST).

Schedule XER import contract sections 9.3 (H4) and 13.2, acceptance C4: every
S7-1 fixture's frame decodes (catalogue-typed, `p6_frame_codec`) to a result
that renders the identical bytes; the parent's classification refuses a frame
bound to other bytes, a non-canonical frame, a frame of another catalogue and
any shape the codec does not know, and shares the S5 exit-code ladder. One
real contained child parses a fixture end to end.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

import pytest

from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.schedule import ScheduleIssueCode
from my_pa.domain.schedule.p6 import frame_bytes, frame_sha256, parse_xer
from my_pa.domain.schedule.p6.frame import frame_object
from my_pa.domain.schedule.p6_frame_codec import P6FrameDecodeError, decode_p6_frame
from my_pa.infrastructure.jobs.schedule_parser_child import EXIT_INPUT, P6_FRAME_MAGIC
from my_pa.infrastructure.jobs.schedule_parser_process import (
    ChildExchange,
    DeterministicFailure,
    ParsedP6Result,
    TransientFailure,
    classify_p6_exchange,
    run_isolated_p6_parse,
)
from tests.fixtures import schedule_p6_xer as xer

_TRANSIENT: Final = TransientFailure(ErrorCode.INTERNAL_ERROR)


def _envelope(data: bytes, frame: object, *, digest_of: bytes | None = None) -> bytes:
    bound = data if digest_of is None else digest_of
    return P6_FRAME_MAGIC + json.dumps(
        {
            "document_sha256": hashlib.sha256(bound).hexdigest(),
            "document_size_bytes": len(bound),
            "frame": frame,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _exchange(output: bytes, returncode: int = 0) -> ChildExchange:
    return ChildExchange(returncode, output, timed_out=False, overflowed=False, pid=1)


@pytest.mark.parametrize("name", sorted(xer.CASES))
def test_every_fixture_frame_decodes_and_renders_the_same_bytes(name: str) -> None:
    case = xer.build(name)
    result = parse_xer(case.data, capture=case.capture)
    decoded = decode_p6_frame(json.loads(frame_bytes(result)))
    assert frame_bytes(decoded) == frame_bytes(result)
    assert frame_sha256(decoded) == frame_sha256(result)
    parsed = classify_p6_exchange(_exchange(_envelope(case.data, frame_object(result))), case.data)
    assert isinstance(parsed, ParsedP6Result)
    assert parsed.frame_sha256 == frame_sha256(result)


def _full() -> tuple[bytes, dict[str, Any]]:
    data = xer.build("full_valid").data
    return data, frame_object(parse_xer(data))


def test_a_frame_forged_for_another_digest_is_refused() -> None:
    data, frame = _full()
    other = xer.build("minimal_valid").data
    forged = _envelope(data, frame, digest_of=other)
    assert classify_p6_exchange(_exchange(forged), data) == _TRANSIENT
    # The same frame, offered for the bytes it really names, is accepted.
    assert isinstance(classify_p6_exchange(_exchange(_envelope(data, frame)), data), ParsedP6Result)


def test_a_non_canonical_frame_is_refused() -> None:
    data, frame = _full()
    canonical = _envelope(data, frame)
    spaced = P6_FRAME_MAGIC + json.dumps(
        json.loads(canonical[len(P6_FRAME_MAGIC) :]), sort_keys=True
    ).encode("ascii")
    assert classify_p6_exchange(_exchange(spaced), data) == _TRANSIENT
    assert classify_p6_exchange(_exchange(canonical[len(P6_FRAME_MAGIC) :]), data) == _TRANSIENT


@pytest.mark.parametrize(
    "tamper",
    [
        "extra_key",
        "missing_key",
        "other_catalogue",
        "unknown_column",
        "hours_as_float_text",
        "unknown_issue_code",
        "count_lies",
    ],
)
def test_a_tampered_frame_is_refused(tamper: str) -> None:
    data, frame = _full()
    if tamper == "extra_key":
        frame["extra"] = 1
    elif tamper == "missing_key":
        del frame["tables"]
    elif tamper == "other_catalogue":
        frame["profile"]["catalogue_version"] = "p6-field-catalogue-v2"
    elif tamper == "unknown_column":
        frame["activities"][0]["columns"]["synthetic"] = "x"
    elif tamper == "hours_as_float_text":
        frame["activities"][1]["columns"]["remaining_hours"] = "4e1"
    elif tamper == "unknown_issue_code":
        frame["issues"].append(
            {
                "bound": None,
                "code": "p6_synthetic",
                "field": None,
                "line": 1,
                "severity": "warning",
                "table": None,
            }
        )
    elif tamper == "count_lies":
        frame["counts"]["activities"] += 1
    if tamper not in {"count_lies"}:
        with pytest.raises(P6FrameDecodeError):
            decode_p6_frame(frame)
    assert classify_p6_exchange(_exchange(_envelope(data, frame)), data) == _TRANSIENT


def test_the_exit_ladder_is_shared_with_the_pdf_child() -> None:
    data = xer.build("full_valid").data
    assert classify_p6_exchange(
        ChildExchange(0, b"", timed_out=False, overflowed=True, pid=1), data
    ) == DeterministicFailure(ScheduleIssueCode.BOUNDS_EXCEEDED)
    assert classify_p6_exchange(
        ChildExchange(None, b"", timed_out=True, overflowed=False, pid=1), data
    ) == DeterministicFailure(ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED)
    assert classify_p6_exchange(_exchange(b"", EXIT_INPUT), data) == DeterministicFailure(
        ScheduleIssueCode.SOURCE_TOO_LARGE
    )
    assert classify_p6_exchange(_exchange(b"", 9), data) == _TRANSIENT


def test_the_contained_child_parses_a_fixture_end_to_end() -> None:
    case = xer.build("udf_all_types")
    parsed = run_isolated_p6_parse(case.data, capture=case.capture, wall_seconds=30)
    assert isinstance(parsed, ParsedP6Result)
    assert frame_bytes(parsed.result) == frame_bytes(parse_xer(case.data, capture=case.capture))


def test_a_malformed_capture_selection_is_the_parents_error() -> None:
    data = xer.build("full_valid").data
    assert run_isolated_p6_parse(data, capture=["not a key"], wall_seconds=30) == _TRANSIENT


def test_a_frame_over_the_output_cap_is_bounds_exceeded() -> None:
    """Section 9.3 H4: the child's frame is capped; past the cap the parse is refused."""
    from my_pa.infrastructure.jobs.schedule_parser_child import ChildLimits

    data = xer.build("full_valid").data
    whole = run_isolated_p6_parse(data, capture=None, wall_seconds=30)
    assert isinstance(whole, ParsedP6Result)
    capped = run_isolated_p6_parse(
        data, capture=None, wall_seconds=30, limits=ChildLimits(output_bytes=1024)
    )
    assert capped == DeterministicFailure(ScheduleIssueCode.BOUNDS_EXCEEDED)
