"""The contained schedule parse: the child, its bounds, and the parent's classification.

S5b-2 worker contract (`docs/architecture/cpm-workbench-worker-capabilities-contract.md`)
sections 3.4.1-3.4.8, S5a U-05 and U-12. FAST: every test starts real child
processes of this interpreter, on synthetic PDFs generated here or by
`tests.fixtures.schedule_full_pdf`, and nothing touches a database.

Probe children are test-only commands reachable **only** through the injectable
`command` (or the module's private `_exchange`); the production path always
runs `CHILD_COMMAND`, which always applies every containment step.

**Linux-only rows.** `RLIMIT_AS` cannot be lowered on macOS (`ValueError`,
measured), so the memory rows -- the address-space headroom measurement, both
positive controls and the decompression bomb -- and the `RLIMIT_AS` row of
`test_child_rlimits_are_set` skip exactly when `sys.platform != "linux"`. On a
macOS host they are "CI-only, not executed on the implementation host", never
a pass (R7-F01, U2-12). An unsettable cap on Linux is not a skip: it is exit 5,
transient, and those tests fail.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import resource
import signal
import sys
import time
import zlib
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Final

import pytest

import my_pa
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.schedule import (
    ScheduleIssueCode,
    SchedulePublicationStatus,
    canonical_json_bytes,
    parse_result_object,
    parse_result_sha256,
)
from my_pa.infrastructure.jobs import schedule_parser_child as child
from my_pa.infrastructure.jobs import schedule_parser_process as process
from my_pa.infrastructure.jobs.schedule_parser_process import (
    CHILD_COMMAND,
    FRAME_MAGIC,
    FRAME_SCHEMA,
    MIN_TEST_WALL_SECONDS,
    PRODUCTION_CHILD_LIMITS,
    ChildExchange,
    ChildLimits,
    DeterministicFailure,
    ParsedResult,
    TransientFailure,
    classify_exchange,
    run_isolated_parse,
)
from my_pa.infrastructure.schedule import parse_full_schedule
from tests.fixtures import schedule_full_pdf as gen

LINUX: Final = sys.platform == "linux"
LINUX_ONLY: Final = pytest.mark.skipif(not LINUX, reason="Linux-only: RLIMIT_AS/VmPeak")
#: A wall long enough for any synthetic case; the production ceiling is 150 s.
WALL: Final = 60.0
BOMB_ADDRESS_SPACE: Final = 268_435_456
SRC_ROOT: Final = str(Path(my_pa.__file__).resolve().parents[1])
TRANSIENT: Final = TransientFailure(ErrorCode.INTERNAL_ERROR)


def _probe(body: str) -> tuple[str, ...]:
    """A test-only child command: this interpreter, isolated, running `body`."""
    return (
        sys.executable,
        "-I",
        "-B",
        "-c",
        "import sys; sys.path.insert(0, sys.argv[1])\n" + body,
    )


def _exchange(
    command: Sequence[str], *args: str, data: bytes = b"", wall: float = 10.0
) -> ChildExchange:
    return process._exchange(
        data,
        [*command, SRC_ROOT, *args],
        wall_seconds=wall,
        output_cap=PRODUCTION_CHILD_LIMITS.output_bytes,
    )


def _small() -> gen.FixtureCase:
    return gen.build("full_valid_2p", "base")


def _largest() -> gen.FixtureCase:
    return gen.build("full_multi_page_86_equivalent", "base")


#: The bounds-maximal synthetic (contract 3.4.8, FR7-F01): the S5a page cap of
#: 250 pages, each holding the most 7-point rows the `p6_full_v1` data zone
#: admits without two rows' glyph boxes overlapping (93 at a 6.4 pt pitch from
#: a 690 pt first baseline), so 23,250 rows -- 93 % of the 25,000-row cap,
#: which 250 pages of this geometry cannot reach. Names are padded so PDFium's
#: character count (1,928,357, measured with pypdfium2 5.0) is 96 % of the
#: 2,000,000-character cap, with a margin so an engine's generated-character
#: accounting cannot tip it over. Measured: 142,749 text objects (57 % of
#: 250,000) and about 12.4 MB (74 % of 16 MiB). Every string is neutral
#: synthetic text; the document is generated at test time and never committed.
BOUNDS_MAXIMAL_PAGES: Final = 250
BOUNDS_MAXIMAL_ROWS_PER_PAGE: Final = 93
_BOUNDS_MAXIMAL_PITCH: Final = gen.D("6.4")
_BOUNDS_MAXIMAL_FIRST_BASELINE: Final = gen.D(690)
_BOUNDS_MAXIMAL_NAME: Final = "Synthetic bounds-maximal activity {:05d} pad"


@functools.cache
def _bounds_maximal() -> gen.FixtureCase:
    plan = gen.Plan()
    pages = [plan.new_page() for _ in range(BOUNDS_MAXIMAL_PAGES)]
    for page in pages:
        plan.frame(page, BOUNDS_MAXIMAL_PAGES)
    index = 0
    for page in pages:
        for line in range(BOUNDS_MAXIMAL_ROWS_PER_PAGE):
            y = _BOUNDS_MAXIMAL_FIRST_BASELINE - _BOUNDS_MAXIMAL_PITCH * line
            if page == 1 and line == 0:
                plan.summary(
                    page,
                    y,
                    0,
                    "Synthetic Project",
                    gen.dur("120"),
                    gen.dur("80"),
                    gen.day(gen._d(5, 4)),
                    gen.day(gen._d(10, 30)),
                )
                continue
            plan.activity(
                page,
                y,
                1,
                f"SYN-{10000 + index}",
                _BOUNDS_MAXIMAL_NAME.format(index),
                gen.dur("10"),
                gen.dur("5"),
                gen.day(gen._d(5, 4)),
                gen.day(gen._d(5, 15)),
            )
            index += 1
    return plan.case("bounds_maximal", "base", gen.COMPLETE)


# ---- hand-built hostile PDFs (stdlib only) ------------------------------------------


def _pdf(objects: Sequence[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def _one_page(resources: bytes, content: bytes, stream_filter: bytes = b"") -> bytes:
    return _pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1224 792] /Resources "
            + resources
            + b" /Contents 4 0 R >>",
            b"<< /Length %d %s>>\nstream\n" % (len(content), stream_filter)
            + content
            + b"\nendstream",
        ]
    )


def _deep_nesting(depth: int = 100_000) -> bytes:
    return _one_page(b"<< /X " + b"[" * depth + b"]" * depth + b" >>", b"BT ET")


def _decompression_bomb() -> bytes:
    """1 page whose `FlateDecode` content inflates to 512 MiB of zeros (~0.5 MiB)."""
    compressor = zlib.compressobj(9)
    zeros = bytes(1 << 20)
    stream = b"".join(compressor.compress(zeros) for _ in range(512)) + compressor.flush()
    return _one_page(b"<< >>", stream, b"/Filter /FlateDecode ")


def _text_flood(operations: int = 200_000) -> bytes:
    """FR7-F04: 1 page, a ~2.6 KB PDF whose Flate content is `BT /F1 1 Tf` and then
    `(x) Tj` 200,000 times with no `Td` (FR7's variant): PDFium spends well over 20 s
    inside one page load on the implementation host (FR7 measured 21.2 s and 21.5 s
    at a 20 s wall)."""
    font = b"<< /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >>"
    content = b"BT /F1 1 Tf " + b"(x) Tj " * operations + b"ET"
    return _one_page(font, zlib.compress(content, 9), b"/Filter /FlateDecode ")


# ---- parity under production limits ---------------------------------------------------


def _parity_cases() -> list[tuple[str, str]]:
    """Every S5a case with distinct bytes, except the oversized-input case."""
    seen: set[str] = set()
    cases = []
    for family, variant in gen.CASES:
        case = gen.build(family, variant)
        if case.sha256 in seen or len(case.pdf) > child.MAX_CHILD_INPUT_BYTES:
            continue
        seen.add(case.sha256)
        cases.append((family, variant))
    return cases


@pytest.mark.parametrize(("family", "variant"), _parity_cases())
def test_child_parse_equals_in_process_parse(family: str, variant: str) -> None:
    """The child path changes nothing: same result, engine and page sizes (AC-009..019).

    Both sides run the production parse limits and the real clock: the S5a
    cases that inject tightened limits or a fake clock are parsed here exactly
    as the child must parse them, so parity holds for every admitted byte string.
    """
    case = gen.build(family, variant)
    expected = parse_full_schedule(case.pdf, expected_data_date=case.expected_data_date)
    outcome = run_isolated_parse(
        case.pdf, expected_data_date=case.expected_data_date, wall_seconds=WALL
    )
    assert isinstance(outcome, ParsedResult), outcome
    assert parse_result_sha256(outcome.result) == parse_result_sha256(expected)
    assert outcome.result == expected


def test_oversized_input_is_source_too_large() -> None:
    oversized = gen.build("bounds_exceeded", "bytes").pdf
    assert len(oversized) > child.MAX_CHILD_INPUT_BYTES
    outcome = run_isolated_parse(oversized, expected_data_date=None, wall_seconds=WALL)
    assert outcome == DeterministicFailure(ScheduleIssueCode.SOURCE_TOO_LARGE)


# ---- the Linux memory rows ------------------------------------------------------------


#: The benign documents the Linux memory rows parse (contract 3.4.8): the
#: largest S5a golden and the bounds-maximal synthetic, with their outcomes.
MEMORY_CASES: Final = {
    "largest_golden": (_largest, SchedulePublicationStatus.REVIEW_REQUIRED),
    "bounds_maximal": (_bounds_maximal, SchedulePublicationStatus.COMPLETE),
}


def test_bounds_maximal_synthetic_is_at_or_near_every_production_cap() -> None:
    """The bounds-maximal case is within production caps and near the binding ones.

    Runs on every platform (the Linux rows below depend on it being what it says).
    """
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    from my_pa.infrastructure.schedule.full_profile import ScheduleParseLimits

    limits = ScheduleParseLimits()
    case = _bounds_maximal()
    draws = [draw for page in case.pages for draw in page.draws]
    assert len(case.pages) == limits.max_pages == BOUNDS_MAXIMAL_PAGES
    assert len(case.truth.rows) == BOUNDS_MAXIMAL_PAGES * BOUNDS_MAXIMAL_ROWS_PER_PAGE
    assert 0.9 * limits.max_rows <= len(case.truth.rows) <= limits.max_rows
    assert len(draws) <= limits.max_text_objects
    assert len(case.pdf) <= limits.max_bytes
    document = pdfium.PdfDocument(case.pdf)
    try:
        characters = 0
        for page in document:
            textpage = page.get_textpage()
            characters += int(pdfium_c.FPDFText_CountChars(textpage.raw))
            textpage.close()
    finally:
        document.close()
    assert 0.95 * limits.max_text_chars <= characters <= limits.max_text_chars, characters


@LINUX_ONLY
@pytest.mark.parametrize("name", MEMORY_CASES)
def test_largest_golden_parses_under_production_limits(name: str) -> None:
    """Positive control: the 1 GiB cap breaks neither the largest golden nor the
    bounds-maximal synthetic (contract 3.4.8, FR7-F01)."""
    build, expected = MEMORY_CASES[name]
    case = build()
    outcome = run_isolated_parse(
        case.pdf, expected_data_date=case.expected_data_date, wall_seconds=WALL
    )
    assert isinstance(outcome, ParsedResult), outcome
    assert outcome.result.outcome is expected
    assert outcome.result == parse_full_schedule(
        case.pdf, expected_data_date=case.expected_data_date
    )


@LINUX_ONLY
def test_benign_document_parses_under_the_bomb_cap() -> None:
    """Positive control: the bomb below fails because of the bomb, not the cap."""
    case = _largest()
    outcome = run_isolated_parse(
        case.pdf,
        expected_data_date=case.expected_data_date,
        wall_seconds=WALL,
        limits=ChildLimits(address_space=BOMB_ADDRESS_SPACE),
    )
    assert isinstance(outcome, ParsedResult), outcome
    assert outcome.result.outcome is SchedulePublicationStatus.REVIEW_REQUIRED


def _failed_code(outcome: process.IsolatedParse) -> ScheduleIssueCode:
    if isinstance(outcome, DeterministicFailure):
        return outcome.code
    assert isinstance(outcome, ParsedResult), outcome
    assert outcome.result.outcome is SchedulePublicationStatus.FAILED
    (issue,) = outcome.result.issues
    return issue.code


@LINUX_ONLY
def test_decompression_bomb_fails_closed_on_linux() -> None:
    bomb = _decompression_bomb()
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    limits = ChildLimits(address_space=BOMB_ADDRESS_SPACE)
    codes = [
        _failed_code(
            run_isolated_parse(bomb, expected_data_date=None, wall_seconds=WALL, limits=limits)
        )
        for _ in range(2)
    ]
    grown_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before
    print(f"decompression bomb outcome: {codes[0].value}")  # the measured member, for the CI log
    assert codes[0] == codes[1]
    assert codes[0] in {ScheduleIssueCode.BOUNDS_EXCEEDED, ScheduleIssueCode.PARSER_EXCEPTION}
    assert grown_kib < 64 * 1024  # Linux `ru_maxrss` is KiB


_HEADROOM_PROBE: Final = """
import resource, time
from my_pa.infrastructure.jobs import schedule_parser_child as c
started = time.monotonic()
c._limit_files()
from my_pa.infrastructure.schedule import parse_full_schedule
limits = c.PRODUCTION_CHILD_LIMITS
# Every production step except RLIMIT_AS/RLIMIT_DATA, so the peak is not censored.
c._limit_process(limits, 60.0)
sys.addaudithook(c._refuse)
data = sys.stdin.buffer.read(c.MAX_CHILD_INPUT_BYTES + 1)
frame = c._frame(parse_full_schedule(data, deadline=started + 59.0))
with open("/proc/self/status", encoding="ascii") as status:
    peak = next(line for line in status if line.startswith("VmPeak:"))
sys.stdout.write(str(int(peak.split()[1]) * 1024) + " " + str(len(frame)))
"""


@LINUX_ONLY
@pytest.mark.parametrize("name", MEMORY_CASES)
def test_child_address_space_has_headroom(name: str) -> None:
    """R7 F01 ruling: 2 x the uncapped `VmPeak` must fit the provisional 1 GiB cap,
    for the largest golden and the bounds-maximal synthetic (FR7-F01)."""
    case = MEMORY_CASES[name][0]()
    exchange = _exchange(_probe(_HEADROOM_PROBE), data=case.pdf, wall=WALL)
    assert exchange.returncode == 0, exchange
    peak, frame_bytes = (int(value) for value in exchange.output.split())
    print(f"child VmPeak bytes [{name}]: {peak} (frame {frame_bytes} bytes)")
    assert 2 * peak <= PRODUCTION_CHILD_LIMITS.address_space


# ---- the S5a bounds and the wall through the child -----------------------------------


#: The flood's wall. Small to keep the test cheap, yet far below the single
#: PDFium call's duration (over 20 s here), so the call reliably outlasts it.
TEXT_FLOOD_WALL: Final = 5.0


def test_text_flood_outlasts_the_wall_and_ends_processing_budget_exceeded() -> None:
    """FR7-F04 (residual U2-13): one native PDFium call outlives the cooperative deadline.

    The in-child deadline (wall - 1 s) cannot interrupt PDFium inside the page
    load, so the child is still in that call at the wall and is ended from
    outside -- by `RLIMIT_CPU` (`SIGXCPU` at ceil(wall) + 1 s CPU) or the parent
    kill at wall + 2 s -- never by itself. The answer is the run-less
    `DeterministicFailure(processing_budget_exceeded)`; the elapsed time is at
    least the wall and at most the wall plus the kill grace. On Linux the
    address-space cap may end it first (`bounds_exceeded`, or `parser_exception`
    for a native allocation crash). Measured on the implementation host: about
    6.05 s, ended by `SIGXCPU`, on every run.
    """
    started = time.monotonic()
    outcome = run_isolated_parse(
        _text_flood(), expected_data_date=None, wall_seconds=TEXT_FLOOD_WALL
    )
    elapsed = time.monotonic() - started
    allowed = {ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED}
    if LINUX:
        allowed |= {ScheduleIssueCode.BOUNDS_EXCEEDED, ScheduleIssueCode.PARSER_EXCEPTION}
    # Run-less: the child produced no result of its own; it was ended from outside.
    assert isinstance(outcome, DeterministicFailure), outcome
    assert outcome.code in allowed, outcome
    if outcome.code is ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED:
        assert elapsed >= TEXT_FLOOD_WALL, elapsed
    assert elapsed <= TEXT_FLOOD_WALL + process.PARENT_KILL_GRACE_SECONDS + 1.0, elapsed


def test_page_count_bound_through_the_child() -> None:
    outcome = run_isolated_parse(
        gen.build("bounds_exceeded", "pages").pdf, expected_data_date=None, wall_seconds=WALL
    )
    assert _failed_code(outcome) is ScheduleIssueCode.BOUNDS_EXCEEDED


def test_deep_nesting_fails_closed() -> None:
    """100,000 nested arrays in `/Resources`: measured `image_only_pdf` (PDFium caps depth)."""
    outcome = run_isolated_parse(_deep_nesting(), expected_data_date=None, wall_seconds=WALL)
    assert _failed_code(outcome) is ScheduleIssueCode.IMAGE_ONLY_PDF


def test_wall_timeout_is_processing_budget_exceeded() -> None:
    """The in-child cooperative deadline (`start + 0`) ends the parse before the parent kill."""
    case = _largest()
    started = time.monotonic()
    outcome = run_isolated_parse(
        case.pdf, expected_data_date=None, wall_seconds=MIN_TEST_WALL_SECONDS
    )
    elapsed = time.monotonic() - started
    assert isinstance(outcome, ParsedResult), outcome
    assert _failed_code(outcome) is ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED
    assert elapsed < MIN_TEST_WALL_SECONDS + process.PARENT_KILL_GRACE_SECONDS


# ---- probe children: kill, crash, output, frame ---------------------------------------


def _reaped(pid: int | None) -> bool:
    assert pid is not None
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True
    return False


def test_hung_child_is_killed_and_reaped() -> None:
    started = time.monotonic()
    exchange = process._exchange(
        b"",
        [*_probe("import time; time.sleep(30)"), SRC_ROOT],
        wall_seconds=MIN_TEST_WALL_SECONDS,
        output_cap=PRODUCTION_CHILD_LIMITS.output_bytes,
    )
    elapsed = time.monotonic() - started
    assert exchange.timed_out
    assert elapsed < MIN_TEST_WALL_SECONDS + process.PARENT_KILL_GRACE_SECONDS + 3.0
    assert _reaped(exchange.pid)
    assert classify_exchange(exchange, b"") == DeterministicFailure(
        ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED
    )


def test_hung_child_through_run_isolated_parse_is_processing_budget_exceeded() -> None:
    outcome = run_isolated_parse(
        b"%PDF-",
        expected_data_date=None,
        wall_seconds=MIN_TEST_WALL_SECONDS,
        command=_probe("import time; time.sleep(30)"),
    )
    assert outcome == DeterministicFailure(ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED)


def test_native_crash_is_parser_exception() -> None:
    outcome = run_isolated_parse(
        b"%PDF-",
        expected_data_date=None,
        wall_seconds=WALL,
        command=_probe("import os, signal; os.kill(os.getpid(), signal.SIGSEGV)"),
    )
    assert outcome == DeterministicFailure(ScheduleIssueCode.PARSER_EXCEPTION)


def test_external_kill_is_transient() -> None:
    outcome = run_isolated_parse(
        b"%PDF-",
        expected_data_date=None,
        wall_seconds=WALL,
        command=_probe("import os, signal; os.kill(os.getpid(), signal.SIGKILL)"),
    )
    assert outcome == TRANSIENT


def test_oversized_output_is_bounds_exceeded() -> None:
    cap = 1 << 20
    body = f"sys.stdout.buffer.write(b'x' * {cap + 1}); sys.stdout.buffer.write(b'y' * {cap})"
    exchange = process._exchange(b"", [*_probe(body), SRC_ROOT], wall_seconds=WALL, output_cap=cap)
    assert exchange.overflowed
    assert len(exchange.output) <= cap + 1
    assert _reaped(exchange.pid)
    outcome = run_isolated_parse(
        b"%PDF-",
        expected_data_date=None,
        wall_seconds=WALL,
        limits=ChildLimits(output_bytes=cap),
        command=_probe(body),
    )
    assert outcome == DeterministicFailure(ScheduleIssueCode.BOUNDS_EXCEEDED)


def test_malformed_frame_is_transient() -> None:
    body = f"sys.stdout.buffer.write({FRAME_MAGIC!r} + b'{{}}')"
    outcome = run_isolated_parse(
        b"%PDF-", expected_data_date=None, wall_seconds=WALL, command=_probe(body)
    )
    assert outcome == TRANSIENT


def test_frame_for_other_bytes_is_transient() -> None:
    """A valid frame for one document never answers for another (digest and size)."""
    sent = _small().pdf
    exchange = process._exchange(
        sent,
        process._argv(
            CHILD_COMMAND,
            expected_data_date=None,
            wall_seconds=WALL,
            limits=PRODUCTION_CHILD_LIMITS,
        ),
        wall_seconds=WALL,
        output_cap=PRODUCTION_CHILD_LIMITS.output_bytes,
    )
    assert isinstance(classify_exchange(exchange, sent), ParsedResult)
    other = sent + b"\n% another document\n"
    assert classify_exchange(exchange, other) == TRANSIENT


def _frame_object(result: object) -> dict[str, object]:
    frame = child._frame(result)
    assert frame.startswith(FRAME_MAGIC)
    decoded = json.loads(frame[len(FRAME_MAGIC) :])
    assert isinstance(decoded, dict)
    return decoded


def _exchange_of(frame: dict[str, object]) -> ChildExchange:
    return ChildExchange(
        returncode=0,
        output=FRAME_MAGIC + canonical_json_bytes(frame),
        timed_out=False,
        overflowed=False,
        pid=None,
    )


def test_non_canonical_frame_is_transient() -> None:
    """Only the canonical round trip refuses a value no domain constructor inspects.

    The contract's example (an `original_duration.value` of `"1.50"`) is refused
    by `ScheduleDurationCell` itself (3-place exponent), so it cannot isolate
    the round-trip check; a row's derived `bbox_normalized` is read by nothing
    but the round trip, so a tampered one isolates it.
    """
    case = _small()
    result = parse_full_schedule(case.pdf)
    frame = _frame_object(result)
    assert classify_exchange(_exchange_of(frame), case.pdf) == ParsedResult(result)
    rows = frame["result"]["rows"]  # type: ignore[index]
    original = rows[0]["bbox_normalized"][0]
    rows[0]["bbox_normalized"][0] = "0.999999" if original != "0.999999" else "0.000001"
    assert classify_exchange(_exchange_of(frame), case.pdf) == TRANSIENT


def test_frame_keys_and_page_dimensions_are_exact() -> None:
    case = _small()
    result = parse_full_schedule(case.pdf)
    good = _frame_object(result)
    for mutate in (
        lambda f: f.update(extra=1),
        lambda f: f.pop("page_dimensions"),
        lambda f: f.update(schema="cpm-workbench-parse-frame-v0"),
        lambda f: f["engine"].update(extra="x"),
        lambda f: f["page_dimensions"].pop(),
        lambda f: f["page_dimensions"][0].__setitem__(1, f["page_dimensions"][0][1] + 1),
        lambda f: f["page_dimensions"].append([999, 1224000, 792000]),
    ):
        frame = json.loads(json.dumps(good))
        mutate(frame)
        assert classify_exchange(_exchange_of(frame), case.pdf) == TRANSIENT


@pytest.mark.parametrize(
    "entries",
    [
        [[2, 1224000, 792000], [1, 1224000, 792000]],
        [[1, 1224000, 792000], [1, 1224000, 792000]],
        [[1, 1224000, 792000], [3, 1224000, 792000], [2, 1224000, 792000]],
    ],
    ids=["descending", "duplicate", "out_of_order_tail"],
)
def test_page_dimensions_are_strictly_increasing(entries: list[list[int]]) -> None:
    """Contract 3.4.2's rule pinned at the decoder itself (FR7-F03).

    Through `classify_exchange` the canonical round trip and the row-page
    equality would also refuse such a frame, so the frame test alone cannot
    show this clause holds; here it is the only refusal on the path.
    """
    increasing = [[1, 1224000, 792000], [2, 1224000, 792000], [3, 1224000, 792000]]
    assert process._page_dimensions(increasing) == dict.fromkeys((1, 2, 3), (1224000, 792000))
    assert process._page_dimensions(entries) is None


def test_non_finite_json_is_transient() -> None:
    exchange = replace(_exchange_of({}), output=FRAME_MAGIC + b'{"schema": NaN}')
    assert classify_exchange(exchange, b"") == TRANSIENT


# ---- the mapping table (contract 3.4.6) -----------------------------------------------


def _ended(
    returncode: int | None, *, timed_out: bool = False, overflowed: bool = False
) -> ChildExchange:
    return ChildExchange(returncode, b"", timed_out=timed_out, overflowed=overflowed, pid=None)


@pytest.mark.parametrize(
    ("exchange", "expected"),
    [
        (_ended(0, overflowed=True), DeterministicFailure(ScheduleIssueCode.BOUNDS_EXCEEDED)),
        (
            _ended(-signal.SIGKILL, timed_out=True),
            DeterministicFailure(ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED),
        ),
        (
            _ended(-signal.SIGXCPU),
            DeterministicFailure(ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED),
        ),
        (_ended(child.EXIT_MEMORY), DeterministicFailure(ScheduleIssueCode.BOUNDS_EXCEEDED)),
        (_ended(child.EXIT_INPUT), DeterministicFailure(ScheduleIssueCode.SOURCE_TOO_LARGE)),
        (_ended(child.EXIT_USAGE), TRANSIENT),
        (_ended(child.EXIT_CONTAINMENT), TRANSIENT),
        *(
            (_ended(-crash), DeterministicFailure(ScheduleIssueCode.PARSER_EXCEPTION))
            for crash in (
                signal.SIGSEGV,
                signal.SIGBUS,
                signal.SIGILL,
                signal.SIGTRAP,
                signal.SIGABRT,
                signal.SIGFPE,
            )
        ),
        (_ended(-signal.SIGKILL), TRANSIENT),
        (_ended(-signal.SIGTERM), TRANSIENT),
        (_ended(1), TRANSIENT),
        (_ended(None), TRANSIENT),
        (_ended(0), TRANSIENT),
    ],
)
def test_every_child_outcome_has_its_class(
    exchange: ChildExchange, expected: process.IsolatedParse
) -> None:
    assert classify_exchange(exchange, b"") == expected


def test_bad_argv_is_exit_usage() -> None:
    exchange = _exchange(CHILD_COMMAND, "not-a-date", "1000", "1", "8", "1")
    assert exchange.returncode == child.EXIT_USAGE
    widened = _exchange(CHILD_COMMAND, "-", "1000", str(1 << 31), "32", "1")
    assert widened.returncode == child.EXIT_USAGE
    assert classify_exchange(exchange, b"") == TRANSIENT


def test_spawn_failure_is_transient() -> None:
    outcome = run_isolated_parse(
        b"%PDF-",
        expected_data_date=None,
        wall_seconds=WALL,
        command=("/nonexistent/interpreter-for-this-test",),
    )
    assert outcome == TRANSIENT


# ---- containment -----------------------------------------------------------------------


_ENVIRONMENT_PROBE: Final = "import os; sys.stdout.write(' '.join(sorted(os.environ)))"


def test_child_environment_is_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://sentinel@db.invalid/x")
    monkeypatch.setenv("I7A_SENTINEL_SECRET", "sentinel-secret-value")
    monkeypatch.setenv("PYTHONPATH", "/sentinel/path")
    exchange = _exchange(_probe(_ENVIRONMENT_PROBE))
    assert exchange.returncode == 0, exchange
    names = set(exchange.output.decode("ascii").split())
    # Interpreter/OS-added only (measured on macOS: `__CF_USER_TEXT_ENCODING`;
    # `LC_CTYPE` is Python's C-locale coercion).
    assert names <= {"LC_CTYPE", "__CF_USER_TEXT_ENCODING"}


_CONTAINMENT_PROBE: Final = """
import json, resource, socket, subprocess
from my_pa.infrastructure.jobs import schedule_parser_child as c
report = c.apply_containment(c.ChildLimits(), 10.0)
attempts = {}
def attempt(name, action):
    try:
        action()
        attempts[name] = "allowed"
    except Exception as error:
        attempts[name] = type(error).__name__ + ":" + str(error)
attempt("socket", lambda: socket.socket())
attempt("write", lambda: open(sys.argv[2] + "/i7a-probe.txt", "w"))
attempt("append", lambda: open(sys.argv[2] + "/i7a-probe.txt", "a"))
attempt("spawn", lambda: subprocess.run(["/usr/bin/true"]))
attempt("read", lambda: open(sys.argv[1] + "/my_pa/__init__.py", "rb").read(1))
names = ("RLIMIT_CORE", "RLIMIT_FSIZE", "RLIMIT_NOFILE", "RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_DATA")
limits = {name: list(resource.getrlimit(getattr(resource, name))) for name in names}
sys.stdout.write(json.dumps(
    {"attempts": attempts, "limits": limits, "memory_capped": report.memory_capped}
))
"""


def _contained(tmp_path: Path) -> dict[str, object]:
    exchange = _exchange(_probe(_CONTAINMENT_PROBE), str(tmp_path))
    assert exchange.returncode == 0, exchange
    report = json.loads(exchange.output)
    assert isinstance(report, dict)
    return report


def test_containment_refuses_network_spawn_and_write(tmp_path: Path) -> None:
    attempts = _contained(tmp_path)["attempts"]
    assert attempts == {
        "socket": "RuntimeError:contained",
        "write": "RuntimeError:contained",
        "append": "RuntimeError:contained",
        "spawn": "RuntimeError:contained",
        "read": "allowed",
    }
    assert not (tmp_path / "i7a-probe.txt").exists()


_WALL_CPU: Final = math.ceil(10.0)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("RLIMIT_CORE", [0, 0]),
        ("RLIMIT_FSIZE", [0, 0]),
        ("RLIMIT_NOFILE", [32, 32]),
        ("RLIMIT_CPU", [_WALL_CPU + 1, _WALL_CPU + 2]),
        pytest.param(
            "RLIMIT_AS",
            [PRODUCTION_CHILD_LIMITS.address_space] * 2,
            marks=LINUX_ONLY,
        ),
    ],
)
def test_child_rlimits_are_set(tmp_path: Path, name: str, expected: list[int]) -> None:
    limits = _contained(tmp_path)["limits"]
    assert isinstance(limits, dict)
    assert limits[name] == expected


def test_containment_reports_the_memory_cap_per_platform(tmp_path: Path) -> None:
    assert _contained(tmp_path)["memory_capped"] is LINUX


class _Recorder:
    """A stand-in for `resource` and `sys` that records instead of applying."""

    def __init__(self, platform: str, *, refuse_memory: bool) -> None:
        self.platform = platform
        self.calls: list[tuple[str, tuple[int, int]]] = []
        self.hooks: list[object] = []
        self._refuse_memory = refuse_memory
        for name in (
            "RLIMIT_CORE",
            "RLIMIT_FSIZE",
            "RLIMIT_AS",
            "RLIMIT_DATA",
            "RLIMIT_NOFILE",
            "RLIMIT_CPU",
        ):
            setattr(self, name, name)

    def setrlimit(self, name: str, value: tuple[int, int]) -> None:
        if self._refuse_memory and name in ("RLIMIT_AS", "RLIMIT_DATA"):
            raise ValueError("current limit exceeds maximum limit")
        self.calls.append((name, value))

    def addaudithook(self, hook: object) -> None:
        self.hooks.append(hook)


def _recorded(monkeypatch: pytest.MonkeyPatch, platform: str, *, refuse_memory: bool) -> _Recorder:
    recorder = _Recorder(platform, refuse_memory=refuse_memory)
    monkeypatch.setattr(child, "resource", recorder)
    monkeypatch.setattr(
        child, "sys", SimpleNamespace(platform=platform, addaudithook=recorder.addaudithook)
    )
    return recorder


def test_child_command_applies_the_address_space_cap_on_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`CHILD_COMMAND` runs `main`, and `main` always applies `RLIMIT_AS` on Linux."""
    assert CHILD_COMMAND[1:4] == ("-I", "-B", "-c")
    assert "schedule_parser_child import main" in CHILD_COMMAND[4]
    recorder = _recorded(monkeypatch, "linux", refuse_memory=False)
    report = child.apply_containment(PRODUCTION_CHILD_LIMITS, 10.0)
    cap = (PRODUCTION_CHILD_LIMITS.address_space,) * 2
    assert ("RLIMIT_AS", cap) in recorder.calls
    assert ("RLIMIT_DATA", cap) in recorder.calls
    assert report.memory_capped is True
    assert recorder.hooks == [child._refuse]


def test_an_unsettable_cap_on_linux_is_a_containment_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _recorded(monkeypatch, "linux", refuse_memory=True)
    with pytest.raises(child.ContainmentError):
        child.apply_containment(PRODUCTION_CHILD_LIMITS, 10.0)


def test_an_unsettable_cap_off_linux_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _recorded(monkeypatch, "darwin", refuse_memory=True)
    assert child.apply_containment(PRODUCTION_CHILD_LIMITS, 10.0).memory_capped is False
    assert ("RLIMIT_NOFILE", (32, 32)) in recorder.calls


# ---- bounds on the injectable knobs ----------------------------------------------------


def test_child_limits_only_tighten() -> None:
    assert ChildLimits() == PRODUCTION_CHILD_LIMITS
    assert PRODUCTION_CHILD_LIMITS.address_space == 1_073_741_824
    assert PRODUCTION_CHILD_LIMITS.open_files == 32
    assert PRODUCTION_CHILD_LIMITS.output_bytes == 134_217_728
    for widened in (
        {"address_space": PRODUCTION_CHILD_LIMITS.address_space + 1},
        {"open_files": 33},
        {"output_bytes": PRODUCTION_CHILD_LIMITS.output_bytes + 1},
        {"open_files": 7},
        {"address_space": 0},
        {"address_space": True},
    ):
        with pytest.raises(ValueError, match="child"):
            ChildLimits(**widened)  # type: ignore[arg-type]
    for wall in (MIN_TEST_WALL_SECONDS - 0.01, 0.0, 150.01):
        with pytest.raises(ValueError, match="wall"):
            run_isolated_parse(b"%PDF-", expected_data_date=None, wall_seconds=wall)


def test_frame_schema_is_the_contract_name() -> None:
    assert FRAME_SCHEMA == "cpm-workbench-parse-frame-v1"
    assert FRAME_MAGIC == b"CPMWB-PARSE-1\n"
    assert hashlib.sha256(_small().pdf).hexdigest() == _small().sha256
    assert (
        parse_result_object(parse_full_schedule(_small().pdf))["schema"]
        == "cpm-full-parse-result-v1"
    )
