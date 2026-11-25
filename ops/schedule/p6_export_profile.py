"""Print the stats-only conformance profile of one P6 XER export (contract section 12).

Usage, from the repository root:

    python ops/schedule/p6_export_profile.py <path-to-export.xer>

Read-only: the file is opened for reading only, at most the section 5.4 file
cap plus one byte is read, and nothing is written anywhere (no database, no
network, no file). The report is one canonical JSON object on stdout built by
`my_pa.domain.schedule.p6.profile` from the same parser and catalogue the
worker uses; it holds counts, lengths, shapes, names and issue codes only,
never a value from the file. Exit code 1 when the verdict is `fail` (or on
an unexpected error, reported by its type only, never its text), 0 for
`pass` or `pass_with_findings`, 2 on a usage error (including a path that is
not a readable regular file). Contract:
`docs/architecture/schedule-xer-import-contract.md` section 12.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

from my_pa.domain.schedule.p6 import P6_LIMITS, export_profile


def _read(path: Path) -> bytes:
    """At most cap + 1 bytes of a regular file (an over-cap file then fails as a bound).

    The type is checked before opening (opening a FIFO would block) and again on
    the open descriptor.
    """
    if not stat.S_ISREG(path.stat().st_mode):
        raise OSError("not a regular file")
    with path.open("rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise OSError("not a regular file")
        return handle.read(P6_LIMITS.file_bytes + 1)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="p6_export_profile")
    parser.add_argument("path", help="the XER export to profile (read-only)")
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as exit_:
        return 2 if exit_.code not in (0, None) else 0
    path = Path(arguments.path)
    try:
        data = _read(path)
    except OSError:
        print("p6_export_profile=refused not a readable regular file", file=sys.stderr)
        return 2
    try:
        report = export_profile(data)
    except Exception as error:
        # The message of an unexpected error may quote the file; only its type is shown.
        print(f"p6_export_profile=error {type(error).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True))
    return 1 if report["verdict"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
