"""The worker side of the contained schedule parse (S5a U-05, U-12).

Contract: `docs/architecture/cpm-workbench-worker-capabilities-contract.md`
sections 3.4.1, 3.4.3, 3.4.4 and 3.4.6. `run_isolated_parse` starts
`schedule_parser_child` with `subprocess.Popen` of the running interpreter --
not `multiprocessing`, whose spawn would re-import the worker's `__main__` and
whose fork would copy a process holding database connections -- feeds it the
admitted bytes on a pipe, reads at most `output_bytes + 1` back, and kills the
whole process group at `wall + 2 s`. One `selectors` loop, no threads; the
child is always reaped.

The answer is exactly one of `ParsedResult`, `DeterministicFailure` (the
publication fails with a safe code) or `TransientFailure` (the attempt is
released and retried within the job's bound), per the mapping of section
3.4.6. The frame is JSON, decoded through the domain constructors and bound to
the bytes sent by their digest and size; it proves the frame's shape and its
binding, not the truth of its rows (residual U2-10).

This module never imports PDFium or the parser package: the parent process
stays free of PDFium state (S5a U-12 resolved by construction).

**P6 XER (S7-3)**, schedule XER import contract sections 9.3 H4 and 13.2:
`run_isolated_p6_parse` runs the same child in its `p6_xer` mode with the
capture selection. The exit classification is shared; the frame is decoded by
`my_pa.domain.schedule.p6_frame_codec` (catalogue-typed, never the parser),
re-rendered canonically and compared byte for byte with what the child wrote,
and bound to the bytes sent by their SHA-256 and size: a frame forged for
other bytes, or not canonical, is refused (transient, as the PDF frame).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import my_pa
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.schedule import (
    ParseResultDecodeError,
    ScheduleIssueCode,
    ScheduleParseEngine,
    ScheduleParseResult,
    parse_result_from_object,
)
from my_pa.domain.schedule.p6.frame import frame_object, frame_sha256
from my_pa.domain.schedule.p6.model import P6ParseResult
from my_pa.domain.schedule.p6_frame_codec import P6FrameDecodeError, decode_p6_frame
from my_pa.infrastructure.jobs.schedule_parser_child import (
    EXIT_CONTAINMENT,
    EXIT_INPUT,
    EXIT_MEMORY,
    EXIT_USAGE,
    FRAME_MAGIC,
    FRAME_SCHEMA,
    MAX_CHILD_OUTPUT_BYTES,
    P6_FRAME_MAGIC,
    P6_MODE,
    PRODUCTION_CHILD_LIMITS,
    ChildLimits,
)

__all__ = [
    "CHILD_BOOTSTRAP",
    "CHILD_COMMAND",
    "EXIT_CONTAINMENT",
    "EXIT_INPUT",
    "EXIT_MEMORY",
    "EXIT_USAGE",
    "FRAME_MAGIC",
    "FRAME_SCHEMA",
    "MAX_CHILD_OUTPUT_BYTES",
    "MIN_TEST_WALL_SECONDS",
    "PARENT_KILL_GRACE_SECONDS",
    "PRODUCTION_CHILD_LIMITS",
    "ChildExchange",
    "ChildLimits",
    "DeterministicFailure",
    "IsolatedP6Parse",
    "IsolatedParse",
    "ParsedP6Result",
    "ParsedResult",
    "TransientFailure",
    "classify_exchange",
    "classify_p6_exchange",
    "run_isolated_p6_parse",
    "run_isolated_parse",
]

CHILD_BOOTSTRAP: Final = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "from my_pa.infrastructure.jobs.schedule_parser_child import main; "
    "raise SystemExit(main(sys.argv[2:]))"
)
#: `-I` ignores every `PYTHON*` variable, the user site and the script
#: directory; `-B` writes no bytecode (a `.pyc` write under `RLIMIT_FSIZE = 0`
#: would die of `SIGXFSZ`).
CHILD_COMMAND: Final[tuple[str, ...]] = (sys.executable, "-I", "-B", "-c", CHILD_BOOTSTRAP)

#: A test may shorten the wall to this and no further (contract 3.4.3, R7-F12).
MIN_TEST_WALL_SECONDS: Final = 1.0
#: The parse wall never exceeds the handler's 150 s ceiling.
_MAX_WALL_SECONDS: Final = 150.0
#: The parent kills the process group this long after the wall.
PARENT_KILL_GRACE_SECONDS: Final = 2.0
#: How long the parent waits to reap a killed child.
_REAP_SECONDS: Final = 5.0
_CHUNK: Final = 65_536

#: Native crash signals: a PDFium fault, including its own allocation-failure
#: abort under `RLIMIT_AS`, is a deterministic `parser_exception` (ruling O-3).
_CRASH_SIGNALS: Final = frozenset(
    {
        signal.SIGSEGV,
        signal.SIGBUS,
        signal.SIGILL,
        signal.SIGTRAP,
        signal.SIGABRT,
        signal.SIGFPE,
    }
)
_FRAME_KEYS: Final = frozenset({"schema", "engine", "page_dimensions", "result"})
_ENGINE_KEYS: Final = frozenset({"pdfium_version", "pypdfium2_version"})
_PAGE_DIMENSION_FIELDS: Final = 3


@dataclass(frozen=True, slots=True)
class ParsedResult:
    """The child returned a result (of any outcome) for exactly the bytes sent."""

    result: ScheduleParseResult


@dataclass(frozen=True, slots=True)
class DeterministicFailure:
    """The document cannot be parsed within the bounds; the publication fails."""

    code: ScheduleIssueCode


@dataclass(frozen=True, slots=True)
class TransientFailure:
    """This attempt failed for a reason that is not the document's; retry."""

    error_code: ErrorCode


type IsolatedParse = ParsedResult | DeterministicFailure | TransientFailure


@dataclass(frozen=True, slots=True)
class ParsedP6Result:
    """S7-3: the child returned a P6 parse (of any outcome) for exactly the bytes sent.

    `frame_sha256` is the domain-separated digest of the canonical frame
    (`frame_sha256`), the run's `parse_result_sha256`.
    """

    result: P6ParseResult
    frame_sha256: str


type IsolatedP6Parse = ParsedP6Result | DeterministicFailure | TransientFailure


@dataclass(frozen=True, slots=True)
class ChildExchange:
    """What one child run produced, before classification.

    `returncode` is `None` only when the child could not be started.
    """

    returncode: int | None
    output: bytes
    timed_out: bool
    overflowed: bool
    pid: int | None


def _source_root() -> str:
    """The parent's own package root, so the child imports exactly this code."""
    return str(Path(my_pa.__file__).resolve().parents[1])


def _argv(
    command: Sequence[str],
    *,
    expected_data_date: date | None,
    wall_seconds: float,
    limits: ChildLimits,
) -> list[str]:
    return [
        *command,
        _source_root(),
        "-" if expected_data_date is None else expected_data_date.isoformat(),
        str(round(wall_seconds * 1000)),
        str(limits.address_space),
        str(limits.open_files),
        str(limits.output_bytes),
    ]


def _spawn(argv: Sequence[str]) -> subprocess.Popen[bytes]:
    """The child: nothing inherited but 0, 1 and 2; no environment; `/` as cwd."""
    return subprocess.Popen(  # noqa: S603 - this interpreter and a fixed bootstrap, no shell
        list(argv),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={},
        cwd="/",
        close_fds=True,
        start_new_session=True,
    )


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)


def _pump(
    process: subprocess.Popen[bytes], data: bytes, *, deadline: float, output_cap: int
) -> tuple[bytearray, bool, bool]:
    """Write `data`, read at most `output_cap + 1` bytes, until EOF, overflow or deadline."""
    stdin, stdout = process.stdin, process.stdout
    if stdin is None or stdout is None:  # pragma: no cover - both are pipes by construction
        raise RuntimeError("the child has no pipes")
    output = bytearray()
    view = memoryview(data)
    written = 0
    os.set_blocking(stdin.fileno(), False)
    with selectors.DefaultSelector() as selector:
        selector.register(stdout.fileno(), selectors.EVENT_READ)
        if view:
            selector.register(stdin.fileno(), selectors.EVENT_WRITE)
        else:
            stdin.close()
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return output, True, False
            for key, _events in selector.select(timeout=remaining):
                if key.fd == stdout.fileno():
                    chunk = os.read(key.fd, min(_CHUNK, output_cap + 1 - len(output)))
                    if not chunk:
                        selector.unregister(key.fd)
                        continue
                    output += chunk
                    if len(output) > output_cap:
                        return output, False, True
                else:
                    try:
                        written += os.write(key.fd, view[written : written + _CHUNK])
                    except BrokenPipeError:
                        written = len(view)
                    if written >= len(view):
                        selector.unregister(key.fd)
                        stdin.close()
    return output, False, False


def _exchange(
    data: bytes,
    argv: Sequence[str],
    *,
    wall_seconds: float,
    output_cap: int,
) -> ChildExchange:
    """Run one child to an end: exit, overflow, or the parent's kill at wall + 2 s."""
    deadline = time.monotonic() + wall_seconds + PARENT_KILL_GRACE_SECONDS
    try:
        process = _spawn(argv)
    except OSError:
        return ChildExchange(None, b"", timed_out=False, overflowed=False, pid=None)
    timed_out = overflowed = False
    output = bytearray()
    try:
        output, timed_out, overflowed = _pump(
            process, data, deadline=deadline, output_cap=output_cap
        )
        if not (timed_out or overflowed):
            try:
                process.wait(timeout=max(deadline - time.monotonic(), 0.0))
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        _kill_group(process)
        process.wait(timeout=_REAP_SECONDS)
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()
    return ChildExchange(
        returncode=process.returncode,
        output=bytes(output),
        timed_out=timed_out,
        overflowed=overflowed,
        pid=process.pid,
    )


def _refuse_constant(_name: str) -> object:
    raise ValueError("not a finite JSON number")


def _decode_frame(output: bytes, data: bytes) -> ScheduleParseResult | None:
    """The frame's result, bound to `data` by digest and size, or `None`."""
    if not output.startswith(FRAME_MAGIC):
        return None
    try:
        frame = json.loads(output[len(FRAME_MAGIC) :], parse_constant=_refuse_constant)
        if not isinstance(frame, dict) or set(frame) != _FRAME_KEYS:
            return None
        if frame["schema"] != FRAME_SCHEMA:
            return None
        engine_object = frame["engine"]
        if not isinstance(engine_object, dict) or set(engine_object) != _ENGINE_KEYS:
            return None
        engine = ScheduleParseEngine(
            pypdfium2_version=str(engine_object["pypdfium2_version"]),
            pdfium_version=str(engine_object["pdfium_version"]),
        )
        if engine_object != {
            "pdfium_version": engine.pdfium_version,
            "pypdfium2_version": engine.pypdfium2_version,
        }:
            return None
        pages = _page_dimensions(frame["page_dimensions"])
        if pages is None:
            return None
        result = parse_result_from_object(frame["result"], engine, pages)
    except (ValueError, TypeError, RecursionError, ParseResultDecodeError):
        return None
    if (result.document_sha256, result.document_size_bytes) != (
        hashlib.sha256(data).hexdigest(),
        len(data),
    ):
        return None
    return result


def _page_dimensions(value: object) -> dict[int, tuple[int, int]] | None:
    """`[[page, width_mpt, height_mpt], ...]`, strictly increasing pages."""
    if not isinstance(value, list):
        return None
    pages: dict[int, tuple[int, int]] = {}
    previous = 0
    for entry in value:
        if (
            not isinstance(entry, list)
            or len(entry) != _PAGE_DIMENSION_FIELDS
            or any(type(item) is not int or item < 1 for item in entry)
            or entry[0] <= previous
        ):
            return None
        previous = entry[0]
        pages[entry[0]] = (entry[1], entry[2])
    return pages


def _classify_exit(exchange: ChildExchange) -> DeterministicFailure | TransientFailure | None:
    """Contract 3.4.6 for everything but a clean exit (`None`: decode the frame)."""
    transient = TransientFailure(ErrorCode.INTERNAL_ERROR)
    if exchange.overflowed:
        return DeterministicFailure(ScheduleIssueCode.BOUNDS_EXCEEDED)
    if exchange.timed_out:
        return DeterministicFailure(ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED)
    returncode = exchange.returncode
    if returncode is None:
        return transient
    if returncode < 0:
        killed_by = -returncode
        if killed_by == signal.SIGXCPU:
            return DeterministicFailure(ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED)
        if killed_by in _CRASH_SIGNALS:
            return DeterministicFailure(ScheduleIssueCode.PARSER_EXCEPTION)
        # SIGKILL not sent by the parent (an OOM killer, an operator) and any
        # other signal say nothing about the document.
        return transient
    if returncode == EXIT_MEMORY:
        return DeterministicFailure(ScheduleIssueCode.BOUNDS_EXCEEDED)
    if returncode == EXIT_INPUT:
        return DeterministicFailure(ScheduleIssueCode.SOURCE_TOO_LARGE)
    if returncode != 0:
        # EXIT_USAGE (a parent programming error), EXIT_CONTAINMENT (the Linux
        # memory cap could not be set) and any other exit code.
        return transient
    return None


def classify_exchange(exchange: ChildExchange, data: bytes) -> IsolatedParse:
    """Contract 3.4.6: every child outcome to parsed, deterministic or transient."""
    failure = _classify_exit(exchange)
    if failure is not None:
        return failure
    result = _decode_frame(exchange.output, data)
    return TransientFailure(ErrorCode.INTERNAL_ERROR) if result is None else ParsedResult(result)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


_P6_ENVELOPE_KEYS: Final = frozenset({"document_sha256", "document_size_bytes", "frame"})


def _decode_p6_frame(output: bytes, data: bytes) -> ParsedP6Result | None:
    """S7-3: the P6 frame's result, canonical and bound to `data`, or `None`.

    The frame is decoded by the catalogue alone, rendered again and compared
    byte for byte with the child's output, so a non-canonical or lossy frame
    is refused as well as one naming other bytes.
    """
    if not output.startswith(P6_FRAME_MAGIC):
        return None
    try:
        envelope = json.loads(output[len(P6_FRAME_MAGIC) :], parse_constant=_refuse_constant)
        if not isinstance(envelope, dict) or set(envelope) != _P6_ENVELOPE_KEYS:
            return None
        if (envelope["document_sha256"], envelope["document_size_bytes"]) != (
            hashlib.sha256(data).hexdigest(),
            len(data),
        ) or type(envelope["document_size_bytes"]) is not int:
            return None
        result = decode_p6_frame(envelope["frame"])
        rendered = P6_FRAME_MAGIC + _canonical(
            {
                "document_sha256": envelope["document_sha256"],
                "document_size_bytes": envelope["document_size_bytes"],
                "frame": frame_object(result),
            }
        )
    except (ValueError, TypeError, RecursionError, P6FrameDecodeError):
        return None
    if rendered != output:
        return None
    return ParsedP6Result(result=result, frame_sha256=frame_sha256(result))


def classify_p6_exchange(exchange: ChildExchange, data: bytes) -> IsolatedP6Parse:
    """S7-3: the shared exit classification, then the P6 frame (contract 3.4.6)."""
    failure = _classify_exit(exchange)
    if failure is not None:
        return failure
    parsed = _decode_p6_frame(exchange.output, data)
    return TransientFailure(ErrorCode.INTERNAL_ERROR) if parsed is None else parsed


def run_isolated_parse(
    data: bytes,
    *,
    expected_data_date: date | None,
    wall_seconds: float,
    limits: ChildLimits = PRODUCTION_CHILD_LIMITS,
    command: Sequence[str] = CHILD_COMMAND,
) -> IsolatedParse:
    """Parse `data` in a contained child and classify what came back.

    `limits` and `command` are injectable for tests only: `ChildLimits` refuses
    any value above production, and `wall_seconds` below
    `MIN_TEST_WALL_SECONDS` (or above 150 s) is refused here.
    """
    if not isinstance(data, bytes):
        raise TypeError("an isolated parse takes the admitted bytes")
    if not isinstance(limits, ChildLimits):
        raise TypeError("an isolated parse takes ChildLimits")
    if not MIN_TEST_WALL_SECONDS <= wall_seconds <= _MAX_WALL_SECONDS:
        raise ValueError("an isolated parse wall is 1 to 150 seconds")
    argv = _argv(
        command, expected_data_date=expected_data_date, wall_seconds=wall_seconds, limits=limits
    )
    exchange = _exchange(data, argv, wall_seconds=wall_seconds, output_cap=limits.output_bytes)
    return classify_exchange(exchange, data)


def _p6_argv(
    command: Sequence[str],
    *,
    capture: Sequence[str] | None,
    wall_seconds: float,
    limits: ChildLimits,
) -> list[str]:
    return [
        *command,
        _source_root(),
        P6_MODE,
        "-" if capture is None else _canonical(list(capture)).decode("ascii"),
        str(round(wall_seconds * 1000)),
        str(limits.address_space),
        str(limits.open_files),
        str(limits.output_bytes),
    ]


def run_isolated_p6_parse(
    data: bytes,
    *,
    capture: Sequence[str] | None,
    wall_seconds: float,
    limits: ChildLimits = PRODUCTION_CHILD_LIMITS,
    command: Sequence[str] = CHILD_COMMAND,
) -> IsolatedP6Parse:
    """S7-3: parse XER `data` in the contained child under `capture` (None = defaults).

    The same child, containment, wall and output cap as `run_isolated_parse`;
    `limits` and `command` are injectable for tests only.
    """
    if not isinstance(data, bytes):
        raise TypeError("an isolated parse takes the admitted bytes")
    if not isinstance(limits, ChildLimits):
        raise TypeError("an isolated parse takes ChildLimits")
    if not MIN_TEST_WALL_SECONDS <= wall_seconds <= _MAX_WALL_SECONDS:
        raise ValueError("an isolated parse wall is 1 to 150 seconds")
    if capture is not None and not all(isinstance(key, str) for key in capture):
        raise TypeError("a capture selection is a sequence of field keys")
    argv = _p6_argv(command, capture=capture, wall_seconds=wall_seconds, limits=limits)
    exchange = _exchange(data, argv, wall_seconds=wall_seconds, output_cap=limits.output_bytes)
    return classify_p6_exchange(exchange, data)
