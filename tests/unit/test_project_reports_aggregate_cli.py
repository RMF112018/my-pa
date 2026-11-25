"""Project reports: the file-level, counts-only aggregate CLI (WP3P-S2; ruling D14).

On synthetic fixtures only: the counts, `--expect` exact match and mismatch
exit codes, the closed output vocabulary, that no fixture cell text, amount,
header or path reaches stdout, that the filename is never consulted (the same
bytes under swapped names give the same counts), and that the committed
evidence expectations are well formed and cited.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.infrastructure.project_reports import aggregate_cli
from my_pa.infrastructure.project_reports.aggregate_cli import (
    EXPECT_SCHEMA,
    CountsOnlyError,
    check_counts_only,
    compare_expected,
    count_template,
    load_expected,
    main,
    summarize_paths,
)
from my_pa.infrastructure.project_reports.pulse_csv import READER_VERSION, prepare_export

ROOT: Final = Path(__file__).resolve().parents[1] / "fixtures" / "project_reports"
FIXTURES: Final = ROOT / "csv"
SIGNATURES: Final = FIXTURES / "signatures"
EXPECTED: Final = ROOT / "expected" / "evidence_aggregate_v1.json"
KEY: Final = re.compile(r"[a-z0-9_]+(\.[a-z0-9_]+)+")


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any], str]:
    code = main(list(argv))
    out = capsys.readouterr().out
    return code, json.loads(out), out


def _counts(*paths: Path, **bound: str) -> dict[str, int]:
    document, ok = summarize_paths(list(paths), {Path(k): v for k, v in bound.items()})
    assert ok
    counts = document["counts"]
    assert isinstance(counts, dict)
    return counts


def test_the_signature_fixtures_aggregate(capsys: pytest.CaptureFixture[str]) -> None:
    code, document, _ = _run(capsys, str(SIGNATURES), "--project-number", f"{SIGNATURES}=SYN-0001")
    assert code == 0
    assert document["tool"] == "project_reports_file_aggregate"
    assert document["reader_version"] == READER_VERSION
    counts = document["counts"]
    assert counts["files.total"] == counts["files.prepared"] == 15
    assert counts["signatures.distinct"] == counts["signatures.registered_distinct"] == 15
    assert counts["derivations.classified"] == 15
    assert counts["rows.data"] == sum(
        counts[f"rows.by_role.{r}"]
        for r in ("detail", "group_header", "grand_total", "spacer", "grouping_only", "malformed")
    )
    assert counts["completeness.populated"] == 13
    assert counts["completeness.valid_empty"] == counts["completeness.grouping_only"] == 1
    assert counts["cross_checks.match"] == 3 and counts["cross_report.match"] == 1
    assert counts["reconciliation.mismatch_total"] == 0
    assert counts["reconciliation.by_view.buyout_summary.column_groups.match"] == 5
    assert counts["reconciliation.by_view.buyout_summary.column_groups.both_empty"] == 10
    assert counts["reconciliation.by_view.manpower.column_groups.match"] == 3
    assert counts["rows.by_view.with_date_closed.group_header_l2"] == 3
    assert counts["rows.by_view.with_date_closed.embedded_line_breaks.crlf"] == 1
    assert counts["identity.by_view.open_outstanding.identity_missing"] == 1
    assert counts["identity.reasons.ambiguous_commitment_co"] == 1
    # 2 padding styles of 1 commitment under 1 code are 1 record.
    assert counts["records.by_family.buyout"] == 1
    assert counts["records.by_family.meeting_items"] == 2
    assert counts["inputs.project_numbers_unmatched"] == 0


def test_rejections_quarantines_and_sources_are_counted() -> None:
    counts = _counts(FIXTURES)
    assert counts["files.rejected"] == 9
    assert counts["rejections.malformed_csv"] == 3 and counts["rejections.invalid_header"] == 4
    assert counts["rejections.not_utf8"] == counts["rejections.nul_byte"] == 1
    assert counts["quarantines.unknown_header_signature"] == 2
    assert counts["quarantines.malformed_ratio_exceeded"] == 1
    assert counts["signatures.unregistered_distinct"] == 2
    assert counts["rows.unclassified"] == 1 + 2 + 3
    assert counts["sources.byte_identical_across_sources"] >= 1
    # Without a bound number every financial cross-check is not_checked.
    assert counts["cross_checks.not_checked"] == 3 and counts["cross_checks.match"] == 0
    assert counts["files.prepared"] + counts["files.rejected"] == counts["files.total"]


def test_a_mismatched_project_number_quarantines() -> None:
    counts = _counts(SIGNATURES, **{str(SIGNATURES): "SYN-0002"})
    assert counts["quarantines.binding_project_number_mismatch"] == 3
    assert counts["cross_checks.mismatch"] == 3
    assert counts["cross_report.not_checked"] == 1


def test_an_unmatched_project_number_directory_is_counted(tmp_path: Path) -> None:
    counts = _counts(SIGNATURES, **{str(tmp_path): "SYN-0001"})
    assert counts["inputs.project_numbers_unmatched"] == 1


def test_byte_identical_files_in_two_sources() -> None:
    counts = _counts(FIXTURES / "sources")
    assert counts["sources.total"] == 2 and counts["sources.byte_identical_across_sources"] == 1
    assert counts["completeness.valid_empty"] == 2


def test_the_filename_is_never_consulted(tmp_path: Path) -> None:
    """The same bytes under swapped names, in the same sources, give the same counts."""
    original = tmp_path / "original"
    swapped = tmp_path / "swapped"
    shutil.copytree(SIGNATURES, original)
    files = sorted(original.glob("*.csv"))
    swapped.mkdir()
    for path, name in zip(files, [p.name for p in reversed(files)], strict=True):
        (swapped / f"20990101-{name}").write_bytes(path.read_bytes())
    assert sorted(p.name for p in swapped.iterdir()) != sorted(p.name for p in files)
    assert _counts(original, **{str(original): "SYN-0001"}) == _counts(
        swapped, **{str(swapped): "SYN-0001"}
    )


def test_a_file_argument_and_a_directory_argument_agree() -> None:
    files = sorted(SIGNATURES.glob("*.csv"))
    assert _counts(*files) == _counts(SIGNATURES) == _counts(SIGNATURES, *files)


# --- --expect ---------------------------------------------------------------


def _expect_file(tmp_path: Path, counts: dict[str, int]) -> Path:
    path = tmp_path / "expected.json"
    path.write_text(json.dumps({"schema": EXPECT_SCHEMA, "counts": counts}), encoding="utf-8")
    return path


def test_expect_match_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    expected = _expect_file(
        tmp_path, {"files.total": 15, "cross_report.match": 1, "rows.by_role.malformed": 0}
    )
    code, document, _ = _run(capsys, str(SIGNATURES), "--expect", str(expected))
    assert code == 0
    assert document["expect"] == {"asserted": 3, "differing": []}


def test_expect_mismatch_exits_non_zero_with_only_keys_and_integers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    expected = _expect_file(tmp_path, {"files.total": 16, "cross_report.match": 1})
    code, document, _ = _run(capsys, str(SIGNATURES), "--expect", str(expected))
    assert code == 1
    assert document["expect"] == {
        "asserted": 2,
        "differing": [{"key": "files.total", "expected": 16, "actual": 15}],
    }


def test_compare_expected_is_exact() -> None:
    counts = {"a.b": 1, "a.c": 0}
    assert compare_expected(counts, {"a.b": 1})["differing"] == []
    assert compare_expected(counts, {"a.b": 2})["differing"] == [
        {"key": "a.b", "expected": 2, "actual": 1}
    ]
    assert compare_expected(counts, {"a.c": 1})["differing"] == [
        {"key": "a.c", "expected": 1, "actual": 0}
    ]


@pytest.mark.parametrize(
    "document",
    [
        {"schema": "other", "counts": {"files.total": 1}},
        {"schema": EXPECT_SCHEMA, "counts": {}},
        {"schema": EXPECT_SCHEMA, "counts": {"files.unknown_key": 1}},
        {"schema": EXPECT_SCHEMA, "counts": {"files.total": "20"}},
        {"schema": EXPECT_SCHEMA, "counts": {"files.total": -1}},
    ],
)
def test_an_invalid_expect_file_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], document: dict[str, object]
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert main([str(SIGNATURES), "--expect", str(path)]) == 2
    assert capsys.readouterr().out == ""


# --- counts only ------------------------------------------------------------


def _cell_texts() -> set[str]:
    texts: set[str] = set()
    for path in sorted(FIXTURES.rglob("*.csv")):
        try:
            plan = prepare_export(path.read_bytes())
        except Exception:  # noqa: S112 - rejected fixtures carry no planned cells
            continue
        for record in plan.records:
            texts.update(cell for cell in record.cells if len(cell) >= 4)
    return texts


def test_stdout_holds_no_cell_text_amount_header_or_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, document, out = _run(capsys, str(FIXTURES))
    for text in _cell_texts():
        if text in {"Open", "Closed"}:  # also closed-vocabulary words (status classes)
            assert f'"{text}"' not in out
            continue
        assert text not in out, text[:40]
    for planted in ("$", "SYN-", "Synthetic", "HYPERLINK", "<script", "Ignore all", " > "):
        assert planted not in out
    assert str(FIXTURES) not in out and ".csv" not in out
    assert set(document["counts"]) == set(count_template())
    assert all(KEY.fullmatch(key) for key in document["counts"])
    assert all(type(value) is int for value in document["counts"].values())


def test_the_counts_only_guard_refuses_a_planted_document() -> None:
    document, _ = summarize_paths([SIGNATURES])
    check_counts_only(document)
    counts = dict(document["counts"])  # type: ignore[call-overload]
    for planted in (
        {**counts, "rows.by_view.Synthetic Vendor A": 1},
        {**counts, "files.total": "15"},
        {**counts, "files.total": True},
        {k: v for k, v in counts.items() if k != "files.total"},
    ):
        with pytest.raises(CountsOnlyError):
            check_counts_only({**document, "counts": planted})
    with pytest.raises(CountsOnlyError):
        check_counts_only({**document, "path": "x"})
    with pytest.raises(CountsOnlyError):
        check_counts_only(
            {**document, "expect": {"asserted": 1, "differing": [{"key": "x", "expected": 1}]}}
        )
    with pytest.raises(CountsOnlyError):
        check_counts_only(
            {
                **document,
                "expect": {
                    "asserted": 1,
                    "differing": [{"key": "files.total", "expected": "cell", "actual": 1}],
                },
            }
        )


def test_main_refuses_to_print_a_document_that_is_not_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real = aggregate_cli.summarize_paths

    def leaky(*args: object, **kwargs: object) -> tuple[dict[str, object], bool]:
        document, ok = real(*args, **kwargs)  # type: ignore[arg-type]
        document["leak"] = "Synthetic Vendor A"
        return document, ok

    monkeypatch.setattr(aggregate_cli, "summarize_paths", leaky)
    with pytest.raises(CountsOnlyError):
        main([str(SIGNATURES)])
    assert "Synthetic" not in capsys.readouterr().out


def test_an_internal_error_is_counted_without_content(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("Synthetic Vendor A")

    monkeypatch.setattr(aggregate_cli, "derive", boom)
    code, document, out = _run(capsys, str(SIGNATURES))
    assert code == 1 and document["counts"]["files.internal_error"] == 15
    assert "Synthetic" not in out


# --- the committed evidence expectations ------------------------------------


def test_the_evidence_expectations_are_well_formed_and_cited() -> None:
    document = json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert document["schema"] == EXPECT_SCHEMA
    counts = load_expected(EXPECTED.read_bytes())
    assert set(counts) <= set(count_template())
    assert set(document["sources"]) == set(counts)
    for key, source in document["sources"].items():
        assert (
            "docs/evidence/pulse/" in source
            or "invariant" in source
            or key.startswith(
                (
                    "reconstruction.",
                    "inputs.",
                    "reconciliation.by_view.reconciliation.column_groups",
                )
            )
        ), key
    cited = {
        m.group(0) for s in document["sources"].values() for m in re.finditer(r"docs/\S+\.md", s)
    }
    for path in cited:
        assert (Path(__file__).resolve().parents[2] / path).is_file(), path
    assert document["not_encoded"] and all(
        set(item) == {"figure", "reason"} for item in document["not_encoded"]
    )
    # Internal consistency of the transcription.
    roles = ("detail", "group_header", "grouping_only", "grand_total", "spacer", "malformed")
    assert sum(counts[f"rows.by_role.{r}"] for r in roles) == counts["rows.data"]
    assert sum(v for k, v in counts.items() if k.startswith("signatures.files_by_view.")) == 20
    assert (
        counts["completeness.populated"]
        + counts["completeness.valid_empty"]
        + counts["completeness.grouping_only"]
        == counts["files.total"]
    )
    for role in ("detail", "grand_total", "spacer", "malformed"):
        per_view = sum(
            v for k, v in counts.items() if k.startswith("rows.by_view.") and k.endswith(f".{role}")
        )
        assert per_view == counts[f"rows.by_role.{role}"], role
    buyout = "reconciliation.by_view.buyout_summary.column_groups"
    headers = counts["rows.by_view.buyout_summary.group_header_l1"]
    assert counts[f"{buyout}.match"] + counts[f"{buyout}.both_empty"] == headers * 5


def test_the_evidence_expectations_match_the_tool_on_nothing_real(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """On synthetic fixtures the evidence file must differ (it describes real files only)."""
    code, document, _ = _run(capsys, str(SIGNATURES), "--expect", str(EXPECTED))
    assert code == 1
    assert document["expect"]["asserted"] == len(load_expected(EXPECTED.read_bytes()))
    assert any(d["key"] == "files.total" for d in document["expect"]["differing"])
