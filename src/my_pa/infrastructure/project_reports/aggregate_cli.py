"""File-level, counts-only aggregate over exported project-report CSV files (ruling D14).

Usage, from a source checkout (never `-I`, which drops `PYTHONPATH`)::

    PYTHONPATH=src python -m my_pa.infrastructure.project_reports.aggregate_cli \\
        [--expect EXPECTED.json] [--project-number DIRECTORY=NUMBER ...] PATH [PATH ...]

A `PATH` is a CSV file or a directory searched recursively for `*.csv`. Each
file's parent directory is its **source** (one export folder of one Project).
No database is used. `--project-number` binds a source directory to the
project number the cross-check of ruling D11 compares against; without it a
financial file's cross-check is `not_checked`.

**The output is counts only.** One JSON document of closed-vocabulary keys and
integers: files, rows by role (overall and per view), signatures by view,
quarantines by reason, rejections by code, reconciliation outcomes in both
evidence units, identity states, line kinds, status classes and records by
family. It never prints a path, a file or folder name, a project number, an
amount, a header or any cell text; the document is checked against its own
closed key set before it is printed (`check_counts_only`).

`--expect` compares every key of the expected file's `counts` with the output
exactly and prints only the differing keys with both integers.

Exit status: `0` on success; `1` when `--expect` differs or a file failed with
an internal error; `2` on a usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from my_pa.domain.project_reports.model import (
    UNCLASSIFIED_COUNT_KEY,
    CompletenessClass,
    DerivationState,
    FamilyView,
    IdentityState,
    QuarantineReason,
    ReconciliationOutcome,
    RecordFamily,
    RejectionCode,
    RowReason,
    RowRole,
    StatusClass,
    TotalScope,
)
from my_pa.infrastructure.project_reports.pulse_csv import (
    MAX_EXPORT_BYTES,
    READER_VERSION,
    REGISTRY,
    DerivationPlan,
    ExportRejectedError,
    ExportTooLargeError,
    FamilyAdapter,
    derive,
    pair_cross_report,
    prepare_export,
)

__all__ = [
    "EXPECT_SCHEMA",
    "TOOL",
    "check_counts_only",
    "compare_expected",
    "count_template",
    "main",
    "summarize_paths",
]

TOOL: Final = "project_reports_file_aggregate"
EXPECT_SCHEMA: Final = "project_reports_evidence_aggregate_v1"

_ADAPTER_OF_VIEW: Final[Mapping[FamilyView, FamilyAdapter]] = {
    adapter.view: adapter for adapter in REGISTRY.values()
}
_VIEW_ROLE_KEYS: Final = (
    "detail",
    "group_header_l1",
    "group_header_l2",
    "grouping_only_l1",
    "grouping_only_l2",
    "grand_total",
    "spacer",
    "malformed",
)
_BREAK_KINDS: Final = ("crlf", "lf", "cr")
_CROSS_CHECK_OUTCOMES: Final = (
    ReconciliationOutcome.MATCH,
    ReconciliationOutcome.MISMATCH,
    ReconciliationOutcome.NOT_CHECKED,
)
_DEGRADED_REASONS: Final = (RowReason.TYPE_ERROR, RowReason.MORE_THAN_4_DECIMALS)
_IDENTITY_REASONS: Final = (
    RowReason.IDENTITY_MISSING,
    RowReason.AMBIGUOUS_IDENTITY,
    RowReason.AMBIGUOUS_COMMITMENT_CO,
)


def count_template() -> dict[str, int]:
    """Every key the aggregate can print, each at zero: the closed output vocabulary."""
    keys: list[str] = [
        "files.total",
        "files.prepared",
        "files.rejected",
        "files.skipped_too_large",
        "files.unreadable",
        "files.internal_error",
        "files.bytes_total",
        "reconstruction.ok",
        "rows.data",
        f"rows.{UNCLASSIFIED_COUNT_KEY}",
        "signatures.distinct",
        "signatures.registered_distinct",
        "signatures.unregistered_distinct",
        "derivations.classified",
        "derivations.quarantined",
        "sources.total",
        "sources.byte_identical_across_sources",
        "inputs.project_numbers_unmatched",
        "reconciliation.mismatch_total",
    ]
    keys += [f"rejections.{code.value}" for code in RejectionCode]
    keys += [f"rows.by_role.{role.value}" for role in RowRole]
    keys += [f"rows.embedded_line_breaks.{kind}" for kind in _BREAK_KINDS]
    keys += [f"quarantines.{reason.value}" for reason in QuarantineReason]
    keys += [f"completeness.{c.value}" for c in CompletenessClass]
    keys += [f"lines.degraded_reasons.{r.value}" for r in _DEGRADED_REASONS]
    keys += [f"identity.{s.value}" for s in IdentityState]
    keys += [f"identity.reasons.{r.value}" for r in _IDENTITY_REASONS]
    keys += [f"records.by_family.{f.value}" for f in RecordFamily]
    keys += [f"cross_report.{o.value}" for o in ReconciliationOutcome]
    keys += [f"cross_checks.{o.value}" for o in _CROSS_CHECK_OUTCOMES]
    for view in FamilyView:
        adapter = _ADAPTER_OF_VIEW[view]
        v = view.value
        keys.append(f"signatures.files_by_view.{v}")
        keys += [f"rows.by_view.{v}.{role}" for role in _VIEW_ROLE_KEYS]
        keys += [f"rows.by_view.{v}.embedded_line_breaks.{kind}" for kind in _BREAK_KINDS]
        keys += [f"completeness.by_view.{v}.{c.value}" for c in CompletenessClass]
        keys += [f"lines.by_view.{v}.typed", f"lines.by_view.{v}.degraded"]
        keys += [f"lines.by_view.{v}.line_kind.{k.value}" for k in adapter.line_kinds]
        keys += [f"identity.by_view.{v}.{s.value}" for s in IdentityState]
        if adapter.status is not None:
            keys += [f"status.by_view.{v}.{s.value}" for s in StatusClass]
        keys += [
            f"reconciliation.by_view.{v}.column_groups.{o.value}" for o in ReconciliationOutcome
        ]
        keys += [
            f"reconciliation.by_view.{v}.groups.checked",
            f"reconciliation.by_view.{v}.groups.all_columns_match",
        ]
        keys += [f"reconciliation.by_view.{v}.grand.{o.value}" for o in ReconciliationOutcome]
    if len(set(keys)) != len(keys):
        raise AssertionError("the count template repeats a key")
    return dict.fromkeys(sorted(keys), 0)


_TEMPLATE_KEYS: Final = frozenset(count_template())


class CountsOnlyError(ValueError):
    """The document holds something other than closed keys and integers."""


def check_counts_only(document: Mapping[str, object]) -> None:
    """Refuse any key outside the closed vocabulary and any value that is not an integer."""
    if set(document) - {"tool", "reader_version", "counts", "expect"}:
        raise CountsOnlyError("unexpected top-level key")
    if document.get("tool") != TOOL or document.get("reader_version") != READER_VERSION:
        raise CountsOnlyError("unexpected metadata")
    counts = document.get("counts")
    if not isinstance(counts, dict) or set(counts) != _TEMPLATE_KEYS:
        raise CountsOnlyError("the counts are not the closed key set")
    if any(type(value) is not int for value in counts.values()):
        raise CountsOnlyError("a count is not an integer")
    expect = document.get("expect")
    if expect is None:
        return
    if not isinstance(expect, dict) or set(expect) != {"asserted", "differing"}:
        raise CountsOnlyError("unexpected expect block")
    if type(expect["asserted"]) is not int or not isinstance(expect["differing"], list):
        raise CountsOnlyError("unexpected expect block")
    for item in expect["differing"]:
        if not isinstance(item, dict) or set(item) != {"key", "expected", "actual"}:
            raise CountsOnlyError("unexpected difference entry")
        if item["key"] not in _TEMPLATE_KEYS:
            raise CountsOnlyError("a difference names an unknown key")
        if any(item[k] is not None and type(item[k]) is not int for k in ("expected", "actual")):
            raise CountsOnlyError("a difference is not an integer")


@dataclass(slots=True)
class _Source:
    plans: list[DerivationPlan]


def _expand(paths: Iterable[Path]) -> list[Path]:
    found: dict[Path, Path] = {}
    for path in paths:
        if path.is_dir():
            candidates = [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".csv"]
        else:
            candidates = [path]
        for candidate in candidates:
            found.setdefault(candidate.resolve(), candidate)
    return [found[key] for key in sorted(found)]


def _role_key(role: RowRole, level: int | None) -> str:
    if role in (RowRole.GROUP_HEADER, RowRole.GROUPING_ONLY):
        return f"{role.value}_l{level}"
    return role.value


def _add_plan(
    counts: Counter[str], plan: DerivationPlan, records: set[tuple[int, str, str]], source: int
) -> None:
    layer_a = plan.layer_a
    counts["rows.data"] += len(layer_a.rows)
    crlf = sum(r.embedded_crlf for r in layer_a.records)
    lf = sum(r.embedded_lf for r in layer_a.records)
    cr = sum(r.embedded_cr for r in layer_a.records)
    for kind, value in zip(_BREAK_KINDS, (crlf, lf, cr), strict=True):
        counts[f"rows.embedded_line_breaks.{kind}"] += value
    adapter = plan.adapter
    if adapter is not None:
        v = adapter.view.value
        for kind, value in zip(_BREAK_KINDS, (crlf, lf, cr), strict=True):
            counts[f"rows.by_view.{v}.embedded_line_breaks.{kind}"] += value
    if plan.state is DerivationState.QUARANTINED:
        counts["derivations.quarantined"] += 1
        if plan.quarantine_reason is not None:
            counts[f"quarantines.{plan.quarantine_reason.value}"] += 1
        counts[f"rows.{UNCLASSIFIED_COUNT_KEY}"] += plan.role_counts[UNCLASSIFIED_COUNT_KEY]
        if plan.cross_check is not None:
            counts[f"cross_checks.{plan.cross_check.value}"] += 1
        return
    if adapter is None:  # a classified plan always has its adapter
        raise AssertionError("a classified derivation without an adapter")
    v = adapter.view.value
    counts["derivations.classified"] += 1
    for row in plan.rows:
        counts[f"rows.by_role.{row.role.value}"] += 1
        counts[f"rows.by_view.{v}.{_role_key(row.role, row.group_level)}"] += 1
    if plan.completeness is not None:
        counts[f"completeness.{plan.completeness.value}"] += 1
        counts[f"completeness.by_view.{v}.{plan.completeness.value}"] += 1
    for line in plan.lines:
        counts[f"lines.by_view.{v}.{line.state.value}"] += 1
        counts[f"lines.by_view.{v}.line_kind.{line.line_kind.value}"] += 1
        for reason in line.reasons:
            counts[f"lines.degraded_reasons.{reason.value}"] += 1
        counts[f"identity.{line.identity.state.value}"] += 1
        counts[f"identity.by_view.{v}.{line.identity.state.value}"] += 1
        if line.identity_reason is not None:
            counts[f"identity.reasons.{line.identity_reason.value}"] += 1
        if line.status_class is not None:
            counts[f"status.by_view.{v}.{line.status_class.value}"] += 1
        if line.identity.state is IdentityState.IDENTIFIED and line.identity.key is not None:
            records.add((source, adapter.family.value, line.identity.key))
    for check in plan.stated_totals:
        unit = "column_groups" if check.scope is TotalScope.GROUP else "grand"
        counts[f"reconciliation.by_view.{v}.{unit}.{check.outcome.value}"] += 1
        if check.outcome is ReconciliationOutcome.MISMATCH:
            counts["reconciliation.mismatch_total"] += 1
    if plan.reconciliation is not None:
        counts[f"reconciliation.by_view.{v}.groups.checked"] += plan.reconciliation.groups_checked
        counts[f"reconciliation.by_view.{v}.groups.all_columns_match"] += (
            plan.reconciliation.groups_all_columns_match
        )
    if plan.cross_check is not None:
        counts[f"cross_checks.{plan.cross_check.value}"] += 1


def summarize_paths(
    paths: Sequence[Path], project_numbers: Mapping[Path, str] | None = None
) -> tuple[dict[str, object], bool]:
    """The counts-only document and whether every file was processed without an internal error."""
    bound = {path.resolve(): number for path, number in (project_numbers or {}).items()}
    files = _expand(paths)
    counts: Counter[str] = Counter()
    sources: dict[Path, int] = {}
    shas: dict[str, set[int]] = {}
    signatures: dict[str, bool] = {}
    by_source: dict[int, _Source] = {}
    records: set[tuple[int, str, str]] = set()
    ok = True
    counts["files.total"] = len(files)
    for path in files:
        parent = path.resolve().parent
        source = sources.setdefault(parent, len(sources))
        try:
            try:
                if path.stat().st_size > MAX_EXPORT_BYTES:
                    counts["files.skipped_too_large"] += 1
                    continue
                data = path.read_bytes()
            except OSError:
                counts["files.unreadable"] += 1
                continue
            counts["files.bytes_total"] += len(data)
            try:
                layer_a = prepare_export(data)
            except ExportTooLargeError:
                counts["files.skipped_too_large"] += 1
                continue
            except ExportRejectedError as rejected:
                counts["files.rejected"] += 1
                counts[f"rejections.{rejected.code.value}"] += 1
                continue
            counts["files.prepared"] += 1
            counts["reconstruction.ok"] += 1
            shas.setdefault(layer_a.file_sha256, set()).add(source)
            plan = derive(layer_a, project_number=bound.get(parent))
            signatures[layer_a.signature] = layer_a.signature in REGISTRY
            if plan.adapter is not None:
                counts[f"signatures.files_by_view.{plan.adapter.view.value}"] += 1
            by_source.setdefault(source, _Source([])).plans.append(plan)
            _add_plan(counts, plan, records, source)
        except Exception:  # one bad file never aborts the batch; no content is printed
            ok = False
            counts["files.internal_error"] += 1
    counts["signatures.distinct"] = len(signatures)
    counts["signatures.registered_distinct"] = sum(1 for known in signatures.values() if known)
    counts["signatures.unregistered_distinct"] = sum(
        1 for known in signatures.values() if not known
    )
    counts["sources.total"] = len(sources)
    counts["sources.byte_identical_across_sources"] = sum(1 for s in shas.values() if len(s) > 1)
    counts["inputs.project_numbers_unmatched"] = sum(1 for p in bound if p not in sources)
    for _source, family, _key in records:
        counts[f"records.by_family.{family}"] += 1
    for entry in by_source.values():
        buyouts = [p for p in entry.plans if _view(p) is FamilyView.BUYOUT_SUMMARY]
        reconciliations = [p for p in entry.plans if _view(p) is FamilyView.RECONCILIATION]
        if not buyouts and not reconciliations:
            continue
        if len(buyouts) == 1 and len(reconciliations) == 1:
            outcome = pair_cross_report(buyouts[0], reconciliations[0]).outcome
        else:
            outcome = ReconciliationOutcome.NOT_CHECKED
        counts[f"cross_report.{outcome.value}"] += 1
    template = count_template()
    unknown = set(counts) - set(template)
    if unknown:
        raise AssertionError("a count key outside the closed vocabulary")
    template.update(counts)
    document: dict[str, object] = {
        "tool": TOOL,
        "reader_version": READER_VERSION,
        "counts": template,
    }
    return document, ok


def _view(plan: DerivationPlan) -> FamilyView | None:
    return plan.adapter.view if plan.adapter is not None else None


class ExpectFileError(ValueError):
    """The expected-figures file is not a valid `project_reports_evidence_aggregate_v1`."""


def load_expected(data: bytes) -> dict[str, int]:
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ExpectFileError("not UTF-8 JSON") from None
    if not isinstance(document, dict) or document.get("schema") != EXPECT_SCHEMA:
        raise ExpectFileError("wrong schema")
    counts = document.get("counts")
    if not isinstance(counts, dict) or not counts:
        raise ExpectFileError("no counts")
    for key, value in counts.items():
        if key not in _TEMPLATE_KEYS or type(value) is not int or value < 0:
            raise ExpectFileError(
                "a count key is unknown or its value is not a non-negative integer"
            )
    return dict(counts)


def compare_expected(counts: Mapping[str, int], expected: Mapping[str, int]) -> dict[str, object]:
    """Exact comparison of every expected key; only differing keys and both integers."""
    differing = [
        {"key": key, "expected": value, "actual": counts.get(key)}
        for key, value in sorted(expected.items())
        if counts.get(key) != value
    ]
    return {"asserted": len(expected), "differing": differing}


def _binding(text: str) -> tuple[Path, str]:
    directory, sep, number = text.rpartition("=")
    if not sep or not directory or not number:
        raise argparse.ArgumentTypeError("expected DIRECTORY=NUMBER")
    return Path(directory), number


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m my_pa.infrastructure.project_reports.aggregate_cli",
        description="Read exported project-report CSV files; print counts-only JSON.",
    )
    parser.add_argument("paths", nargs="+", type=Path, metavar="PATH")
    parser.add_argument("--expect", type=Path, metavar="EXPECTED_JSON")
    parser.add_argument(
        "--project-number", action="append", type=_binding, default=[], metavar="DIRECTORY=NUMBER"
    )
    arguments = parser.parse_args(argv)
    expected: dict[str, int] | None = None
    if arguments.expect is not None:
        try:
            expected = load_expected(arguments.expect.read_bytes())
        except (OSError, ExpectFileError):
            sys.stderr.write("error: the --expect file is unreadable or invalid\n")
            return 2
    document, ok = summarize_paths(arguments.paths, dict(arguments.project_number))
    differs = False
    if expected is not None:
        comparison = compare_expected(cast("dict[str, int]", document["counts"]), expected)
        document["expect"] = comparison
        differs = bool(comparison["differing"])
    check_counts_only(document)
    sys.stdout.write(json.dumps(document, indent=1, sort_keys=True) + "\n")
    return 1 if differs or not ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
