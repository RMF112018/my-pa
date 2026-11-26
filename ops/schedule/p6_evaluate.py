"""Print the stats-only S7-5 evaluation of one or more P6 XER exports (contract section 14).

Usage, from the repository root:

    python ops/schedule/p6_evaluate.py <export.xer> [<export2.xer> ...]

    python ops/schedule/p6_evaluate.py --assume-same-project <v1.xer> <v2.xer> ...

Give consecutive versions of one Project in order (oldest first): each
consecutive pair of exports of the same Project (section 11.1: same project
short name or GUID) is compared `earlier -> later` with the pure P6 delta.
P6 update files exported as separate project copies carry another project
id, short name and GUID, so 11.1 calls them different projects:
`--assume-same-project` compares every consecutive pair anyway. Each pair
reports `same_project` (the 11.1 rule), so a `false` shows that importing the
later file into the same Series needs `accept_project_identity_change`.

Read-only: each file is opened for reading only, at most the section 5.4 file
cap plus one byte is read, and nothing is written anywhere (no database, no
network, no file). The output is ONE canonical JSON object on stdout for the
whole run, built by `my_pa.domain.schedule.p6` (the conformance profile, the
parse, the section 11.5 snapshot and the oracle of `p6.oracle`): counts,
shares, minute distributions, codes and catalogue names only, never a value
from a file. Per export: the profile verdict and issue counts by code, the
activity / relationship / WBS / calendar counts and whether they equal the
records of the file's own tables, the snapshot report counts, and the
engine-vs-P6 oracle (a check, never a claim of equivalence). Per consecutive
pair: the delta's counts by change kind.

Exit code 1 when any export's verdict is `fail` (the object is still printed)
or on an unexpected error (reported by its type only, never its text), 0
otherwise, 2 on a usage error (including a path that is not a readable regular
file). Contract: `docs/architecture/schedule-xer-import-contract.md` sections
11.5, 12 and 14; runbook `ops/runbooks/cpm-workbench.md`.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from my_pa.domain.schedule.p6 import P6_LIMITS, P6Outcome, P6ParseResult, parse_xer
from my_pa.domain.schedule.p6.oracle import (
    ORACLE_CAPTURE,
    delta_counts,
    evaluation_snapshot,
    oracle_report,
    same_project,
    snapshot_report,
)
from my_pa.domain.schedule.p6.profile import profile_report
from my_pa.domain.schedule.scenario.p6_snapshot import P6SnapshotRefusalError

EVALUATION_SCHEMA: Final = "p6-evaluation-v1"
#: Entity -> the file table whose records it must equal.
_TABLES: Final = (
    ("activities", "TASK"),
    ("relationships", "TASKPRED"),
    ("wbs", "PROJWBS"),
    ("calendars", "CALENDAR"),
)


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


def _counts(result: P6ParseResult) -> dict[str, Any]:
    """Parsed entities against the records of the file's own table (first of its name)."""
    records: dict[str, int] = {}
    for observed in result.tables:
        if observed.name is not None and observed.name not in records:
            records[observed.name] = observed.records
    parsed = {
        "activities": len(result.activities),
        "relationships": len(result.relationships),
        "wbs": len(result.wbs),
        "calendars": len(result.calendars),
    }
    found: dict[str, Any] = {}
    for name, table in _TABLES:
        file_records = records.get(table)
        found[name] = {
            "equal": file_records is not None and file_records == parsed[name],
            "file": file_records,
            "parsed": parsed[name],
        }
    return found


def _export(position: int, data: bytes) -> tuple[dict[str, Any], P6ParseResult]:
    """One export's object and its default-capture parse (the one the delta reads)."""
    result = parse_xer(data, limits=P6_LIMITS)
    profile = profile_report(result)
    report: dict[str, Any] = {
        "export_version_tested": profile["export_version_tested"],
        "issue_counts": profile["issue_counts"],
        "position": position,
        "verdict": profile["verdict"],
    }
    if result.outcome is not P6Outcome.COMPLETE:
        report |= {"counts": None, "oracle": None, "snapshot": None}
        return report, result
    report["counts"] = _counts(result)
    # The oracle's parse captures only the one option it reads (multiple float paths).
    oracle_parse = parse_xer(data, capture=ORACLE_CAPTURE, limits=P6_LIMITS)
    try:
        report["snapshot"] = {
            "refusal": None,
            **snapshot_report(evaluation_snapshot(oracle_parse)),
        }
    except P6SnapshotRefusalError as refused:
        report["snapshot"] = {"refusal": refused.reason.value}
    report["oracle"] = oracle_report(oracle_parse)
    return report, result


def _pairs(results: Sequence[P6ParseResult], *, assume_same: bool = False) -> list[dict[str, Any]]:
    """Each consecutive pair, `earlier -> later`; a run of one project shares a history.

    P6 update files are often exported as separate project copies, so the identity rule of
    contract 11.1 (same short name or GUID) calls them different projects; `assume_same`
    pairs them anyway (the client would send `accept_project_identity_change`).
    """
    pairs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index in range(1, len(results)):
        earlier, later = results[index - 1], results[index]
        pair: dict[str, Any] = {"from": index, "to": index + 1}
        complete = all(item.outcome is P6Outcome.COMPLETE for item in (earlier, later))
        if not complete:
            pairs.append({**pair, "delta": None, "same_project": None, "status": "parse_failed"})
            seen = set()
            continue
        # Whether 11.1 matches: false means an import needs `accept_project_identity_change`.
        pair["same_project"] = same_project(earlier, later)
        if not assume_same and not pair["same_project"]:
            pairs.append({**pair, "delta": None, "status": "different_project"})
            seen = set()
            continue
        pairs.append(
            {**pair, "delta": delta_counts(earlier, later, frozenset(seen)), "status": "compared"}
        )
        seen |= {str(item.get("activity_id")) for item in earlier.activities}
    return pairs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="p6_evaluate")
    parser.add_argument("paths", nargs="+", help="the XER exports, oldest first (read-only)")
    parser.add_argument(
        "--assume-same-project",
        action="store_true",
        help="compare consecutive exports even when the 11.1 identity rule says another project",
    )
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as exit_:
        return 2 if exit_.code not in (0, None) else 0
    try:
        files = [_read(Path(path)) for path in arguments.paths]
    except OSError:
        print("p6_evaluate=refused not a readable regular file", file=sys.stderr)
        return 2
    try:
        exports: list[dict[str, Any]] = []
        results: list[P6ParseResult] = []
        for position, data in enumerate(files, start=1):
            report, result = _export(position, data)
            exports.append(report)
            results.append(result)
        document = {
            "exports": exports,
            "pairs": _pairs(results, assume_same=arguments.assume_same_project),
            "schema": EVALUATION_SCHEMA,
        }
        text = json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True)
    except Exception as error:
        # The message of an unexpected error may quote a file; only its type is shown.
        print(f"p6_evaluate=error {type(error).__name__}", file=sys.stderr)
        return 1
    print(text)
    return 1 if any(item["verdict"] == "fail" for item in exports) else 0


if __name__ == "__main__":
    sys.exit(main())
