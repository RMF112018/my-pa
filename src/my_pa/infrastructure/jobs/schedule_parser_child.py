"""The contained child that parses one schedule PDF and exits (S5a U-05, U-12).

Contract: `docs/architecture/cpm-workbench-worker-capabilities-contract.md`
section 3.4. The worker parent (`schedule_parser_process`) starts this module
with `subprocess.Popen` of its own interpreter in isolated mode (`-I -B`), an
empty environment, `cwd = "/"`, only descriptors 0, 1 and 2, and `stderr`
discarded. The child reads the admitted bytes from `stdin`, parses them with
the unchanged S5a entry point `parse_full_schedule`, writes one frame to
`stdout` and exits. It processes exactly one document, so PDFium is never
shared by threads or reused across documents, and the parent never loads
PDFium at all.

**Containment, in order** (`main`):

1. `RLIMIT_CORE = RLIMIT_FSIZE = 0`: no core file, and no write -- native code
   included -- can grow a regular file past 0 bytes. It does not stop native
   code from truncating, unlinking, renaming or creating empty files the worker
   UID may modify (residual U2-10).
2. argv is validated (exit `EXIT_USAGE`), then the parser is imported, which
   loads PDFium before the descriptor cap.
3. On Linux `RLIMIT_AS = RLIMIT_DATA = limits.address_space`; failure to set it
   is exit `EXIT_CONTAINMENT`. macOS refuses to lower `RLIMIT_AS` (`ValueError`,
   measured), so there the cap is reported as not in force. Then
   `RLIMIT_NOFILE` and `RLIMIT_CPU` (`ceil(wall) + 1` soft, `+ 2` hard).
4. An audit hook refuses every Python-level socket, process spawn, exec,
   `ctypes.dlopen`, and any `open` that writes, appends, creates or updates.
   Read-only `open` stays allowed (lazy standard-library imports).
5. At most 16 MiB is read from `stdin` (more is exit `EXIT_INPUT`); the parse
   runs against an in-child cooperative deadline `start + max(wall - 1, 0)`;
   `MemoryError` is exit `EXIT_MEMORY` with nothing written.
6. The frame `FRAME_MAGIC + canonical JSON` is written to `stdout`; exit 0.

**What is not enforced** (contract 3.4.5): native PDFium code issuing raw
socket system calls after memory corruption (U2-01), native file effects that
do not grow a file, and a forged but well-formed frame (U2-10). The mitigations
are operator-level.

This module imports only the standard library at module level and the
`my_pa.domain.schedule` / `my_pa.infrastructure.schedule` packages inside
`main`. It prints nothing and writes nothing but the frame.
"""

from __future__ import annotations

import math
import os
import resource
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import date
from typing import Final

__all__ = [
    "EXIT_CONTAINMENT",
    "EXIT_INPUT",
    "EXIT_MEMORY",
    "EXIT_USAGE",
    "FRAME_MAGIC",
    "FRAME_SCHEMA",
    "MAX_CHILD_INPUT_BYTES",
    "MAX_CHILD_OUTPUT_BYTES",
    "PRODUCTION_CHILD_LIMITS",
    "ChildLimits",
    "ContainmentError",
    "ContainmentReport",
    "apply_containment",
    "main",
]

FRAME_MAGIC: Final = b"CPMWB-PARSE-1\n"
FRAME_SCHEMA: Final = "cpm-workbench-parse-frame-v1"

#: Exit codes the parent classifies (contract 3.4.6).
EXIT_MEMORY: Final = 3
EXIT_INPUT: Final = 4
EXIT_CONTAINMENT: Final = 5
EXIT_USAGE: Final = 6

#: The S5a input bound (16 MiB); one more byte is read to detect an excess.
MAX_CHILD_INPUT_BYTES: Final = 16_777_216
#: The parent's read cap on the frame, magic included (contract 3.4.4).
MAX_CHILD_OUTPUT_BYTES: Final = 134_217_728

#: Production containment values. `address_space` is **provisional** (S5b-2
#: residual U2-12): 1 GiB has not been measured on Linux, where alone it is
#: enforced. `test_child_address_space_has_headroom` measures `VmPeak` in the
#: PR's ubuntu CI and fails below 2x headroom; until a CI run shows it executed
#: and passed, no number here is a measurement.
_PRODUCTION_VALUES: Final[dict[str, int]] = {
    "address_space": 1_073_741_824,
    "open_files": 32,
    "output_bytes": MAX_CHILD_OUTPUT_BYTES,
}
#: The fewest descriptors a test may grant: 0, 1, 2 and PDFium's own.
_MIN_OPEN_FILES: Final = 8

_WRITE_MODE_CHARACTERS: Final = frozenset("wax+")
_WRITE_FLAGS: Final = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_REFUSED_EVENTS: Final = frozenset(
    {
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.fork",
        "os.forkpty",
        "os.spawn",
        "ctypes.dlopen",
    }
)


@dataclass(frozen=True, slots=True)
class ChildLimits:
    """The child's containment bounds. An instance may only tighten production."""

    address_space: int = _PRODUCTION_VALUES["address_space"]
    open_files: int = _PRODUCTION_VALUES["open_files"]
    output_bytes: int = _PRODUCTION_VALUES["output_bytes"]

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if type(value) is not int or value < 1:
                raise ValueError("child limits are positive integers")
            if value > _PRODUCTION_VALUES[item.name]:
                raise ValueError("child limits may only tighten production values")
        if self.open_files < _MIN_OPEN_FILES:
            raise ValueError("a child keeps at least 8 descriptors")


PRODUCTION_CHILD_LIMITS: Final = ChildLimits()


class ContainmentError(Exception):
    """A containment step that must hold could not be applied (exit 5)."""


@dataclass(frozen=True, slots=True)
class ContainmentReport:
    """Whether the address-space cap is in force on this platform."""

    memory_capped: bool


def _limit_files() -> None:
    """Part 1: no core file, and no regular file may grow past 0 bytes."""
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))


def _limit_memory(limits: ChildLimits) -> ContainmentReport:
    """Part 2a: the address-space cap; mandatory on Linux, reported elsewhere."""
    cap = (limits.address_space, limits.address_space)
    try:
        resource.setrlimit(resource.RLIMIT_AS, cap)
        resource.setrlimit(resource.RLIMIT_DATA, cap)
    except (ValueError, OSError):
        # Read into a `str` first: mypy treats a literal `sys.platform == ...`
        # as a static platform check, so under `--platform linux` (CI) it would
        # mark the `return` below unreachable. The runtime test is unchanged.
        platform: str = sys.platform
        if platform == "linux":
            raise ContainmentError("the address-space cap could not be set") from None
        return ContainmentReport(memory_capped=False)
    return ContainmentReport(memory_capped=True)


def _limit_process(limits: ChildLimits, wall_seconds: float) -> None:
    """Part 2b: the descriptor cap and the CPU cap derived from the wall."""
    resource.setrlimit(resource.RLIMIT_NOFILE, (limits.open_files, limits.open_files))
    cpu = math.ceil(wall_seconds)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu + 1, cpu + 2))


def _writes(mode: object, flags: object) -> bool:
    if isinstance(mode, str) and _WRITE_MODE_CHARACTERS & set(mode):
        return True
    if isinstance(flags, int):
        return bool(flags & _WRITE_FLAGS)
    return False


def _refuse(event: str, args: tuple[object, ...]) -> None:
    """The audit hook: refuse network, process, native-load and file-write events."""
    if event.startswith("socket.") or event in _REFUSED_EVENTS:
        raise RuntimeError("contained")
    if event == "open" and len(args) >= 3 and _writes(args[1], args[2]):
        raise RuntimeError("contained")


def apply_containment(limits: ChildLimits, wall_seconds: float) -> ContainmentReport:
    """Apply every containment step: files, memory, descriptors, CPU, audit hook.

    Called once the parser is imported. Re-applying part 1 is idempotent, so a
    caller that skipped the early call still ends fully contained. Raises
    `ContainmentError` when the Linux address-space cap cannot be set.
    """
    _limit_files()
    report = _limit_memory(limits)
    _limit_process(limits, wall_seconds)
    sys.addaudithook(_refuse)
    return report


@dataclass(frozen=True, slots=True)
class _Arguments:
    expected_data_date: date | None
    wall_seconds: float
    limits: ChildLimits


def _arguments(args: Sequence[str]) -> _Arguments:
    """`<expected date or "-"> <wall ms> <address space> <open files> <output bytes>`."""
    if len(args) != 5:
        raise ValueError("usage")
    expected, wall_ms, address_space, open_files, output_bytes = args
    wall = int(wall_ms)
    if wall < 1:
        raise ValueError("usage")
    return _Arguments(
        expected_data_date=None if expected == "-" else date.fromisoformat(expected),
        wall_seconds=wall / 1000,
        limits=ChildLimits(
            address_space=int(address_space),
            open_files=int(open_files),
            output_bytes=int(output_bytes),
        ),
    )


def _frame(result: object) -> bytes:
    """The one frame: magic, then the canonical JSON of schema, engine, pages and result."""
    from my_pa.domain.schedule import (
        ScheduleParseResult,
        canonical_json_bytes,
        parse_result_object,
    )

    if not isinstance(result, ScheduleParseResult):
        raise TypeError("a frame carries a parse result")
    pages = sorted(
        {(row.page_number, row.page_width_mpt, row.page_height_mpt) for row in result.rows}
    )
    return FRAME_MAGIC + canonical_json_bytes(
        {
            "schema": FRAME_SCHEMA,
            "engine": {
                "pdfium_version": result.engine.pdfium_version,
                "pypdfium2_version": result.engine.pypdfium2_version,
            },
            "page_dimensions": [list(page) for page in pages],
            "result": parse_result_object(result),
        }
    )


def main(args: Sequence[str]) -> int:
    """Contain, read, parse, frame. Returns the exit code (contract 3.4.2)."""
    started = time.monotonic()
    _limit_files()
    try:
        arguments = _arguments(args)
    except ValueError:
        return EXIT_USAGE
    from my_pa.infrastructure.schedule import (
        parse_full_schedule,
    )

    try:
        apply_containment(arguments.limits, arguments.wall_seconds)
    except ContainmentError:
        return EXIT_CONTAINMENT
    data = sys.stdin.buffer.read(MAX_CHILD_INPUT_BYTES + 1)
    if len(data) > MAX_CHILD_INPUT_BYTES:
        return EXIT_INPUT
    try:
        result = parse_full_schedule(
            data,
            expected_data_date=arguments.expected_data_date,
            deadline=started + max(arguments.wall_seconds - 1.0, 0.0),
        )
        frame = _frame(result)
    except MemoryError:
        return EXIT_MEMORY
    sys.stdout.buffer.write(frame)
    sys.stdout.buffer.flush()
    return 0
