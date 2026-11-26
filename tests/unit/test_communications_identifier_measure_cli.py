"""The identifier measurement (WP4 ruling D3): counts only, exit status, no leak.

`measure_identifiers` is checked against a synthetic publication whose counts
are known by construction; the CLI is run as the Manager will run it, on files,
and its output must hold no subject, text, address, identifier value or file
name (the `aggregate_cli` canary method). Every value is synthetic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from my_pa.domain.communications.identifiers import IdentifierKind
from my_pa.domain.communications.measurement import measure_identifiers
from my_pa.domain.communications.model import Publication
from my_pa.infrastructure.communications.evidence_v2 import parse_publication
from my_pa.infrastructure.communications.identifier_measure_cli import main, measure_files
from tests.fixtures.communications_evidence import synthetic as s
from tests.unit.test_communications_aggregate_cli import CANARIES, canary_publication

SRC = Path(__file__).resolve().parents[2] / "src"
MODULE = "my_pa.infrastructure.communications.identifier_measure_cli"

#: `(subject, plain-text body)` per record, with what each contributes.
RECORDS = (
    # pco (acronym) and co (words): gained by v2.
    ("PCO 12 approved", "Change Order 5 follows."),
    # co (acronym): found by both versions.
    ("Synthetic", "CO 7 is closed."),
    # The spaced submittal: v1 reads submittal:03, v2 submittal:033000-01 -- both a submittal.
    ("Synthetic", "Submittal 03 30 00-01 attached."),
    # A keyword without a number, and an unsupported lower-case `fpl`.
    ("Synthetic", "See the submittal log; the fpl outage moved."),
    # An RFI only in the quoted chain, which the stored text cuts.
    ("Synthetic", "Please review the plan.\n\nOn Monday, Bravo wrote:\n> RFI 999 is open"),
    # A mid-body "Disclaimer" line: v1 cuts the body (and its RFI), v2 keeps it.
    ("Synthetic", "Hi team,\nDisclaimer language for RFI 12 is attached.\n\nThanks"),
    # A cor in words and FP&L.
    ("Synthetic", "Change Order Request 3 from FP&L."),
)


def publication_document() -> dict[str, Any]:
    return s.publication(
        [
            s.message(n, subject=subject, content=body, content_type="text")
            for n, (subject, body) in enumerate(RECORDS, start=1)
        ],
        s.window("2026-11-17T05:00:00Z", "2026-11-18T04:59:59Z", 24, "weekday_prior_24h"),
        rich=True,
    )


def parsed() -> Publication:
    publication = parse_publication(s.encode(publication_document())).publication
    assert publication is not None
    return publication


def test_the_measurement_counts_by_construction() -> None:
    measured = measure_identifiers([parsed()])
    assert measured.publications == 1
    assert measured.records == len(RECORDS)
    kinds = measured.kinds
    assert set(kinds) == {kind.value for kind in IdentifierKind}
    pco, co, cor = kinds["pco"], kinds["co"], kinds["cor"]
    assert (pco.records_v1, pco.records_v2, pco.records_v2_only) == (0, 1, 1)
    assert dict(pco.by_form_class_v2) == {"pco.acronym": 1}
    assert (co.records_v1, co.records_v2, co.records_v2_only, co.records_v1_only) == (1, 2, 1, 0)
    assert dict(co.by_form_class_v2) == {"co.acronym": 1, "co.words": 1}
    assert (cor.records_v2, dict(cor.by_form_class_v2)) == (1, {"cor.words": 1})
    submittal = kinds["submittal"]
    assert (submittal.records_v1, submittal.records_v2) == (1, 1)
    assert dict(submittal.by_form_class_v2) == {"submittal.spaced_spec": 1}
    assert submittal.records_keyword_without_number == 1
    fpl = kinds["fpl"]
    assert (fpl.records_v2, dict(fpl.by_form_class_v2)) == (1, {"fpl.ampersand": 1})
    assert fpl.records_unsupported_shape == 1
    assert co.records_unsupported_shape is None  # not measured for `co`
    rfi = kinds["rfi"]
    # RFI 12 is in v2's text only (v1 cut it); RFI 999 only in the quoted chain.
    assert (rfi.records_v1, rfi.records_v2, rfi.records_v2_only) == (0, 1, 1)
    assert rfi.records_quoted_or_tail_only == 1
    assert rfi.occurrences_v2 == 1
    assert measured.disclaimer_removed == {"comms_search_text_v1": 1, "comms_search_text_v2": 0}


def test_main_prints_counts_and_exits_zero_when_every_file_is_accepted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "a-comms.json"
    path.write_bytes(s.encode(publication_document()))
    assert main([str(path)]) == 0
    document = json.loads(capsys.readouterr().out)
    assert (document["files"], document["accepted"], document["rejected"]) == (1, 1, 0)
    assert document["identifier_versions"] == ["comms_identifiers_v1", "comms_identifiers_v2"]
    assert document["kinds"]["pco"]["records_v2"] == 1
    assert set(document["kinds"]["pco"]["gap"]) == {
        "records_quoted_or_tail_only",
        "records_keyword_without_number",
        "records_unsupported_shape",
    }


def test_a_rejected_or_unreadable_file_is_counted_and_never_described(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_bytes(s.encode(publication_document()))
    broken = tmp_path / "broken.json"
    broken.write_bytes(b'{"x": [')
    document, all_accepted = measure_files([good, broken, tmp_path / "missing.json"])
    assert not all_accepted
    assert (document["files"], document["accepted"], document["rejected"]) == (3, 1, 2)
    assert "broken" not in json.dumps(document)


def test_no_arguments_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main([])
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""


def test_the_cli_output_contains_no_canary_value_or_file_name(tmp_path: Path) -> None:
    canary = tmp_path / "CANARY-FILE-comms.json"
    canary.write_bytes(s.encode(canary_publication()))
    values = tmp_path / "values.json"
    values.write_bytes(s.encode(publication_document()))
    malformed = tmp_path / "broken.json"
    malformed.write_bytes(b'{"subject": "CANARY-SUBJECT-xyz", "x": [')
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and module, synthetic paths
        [sys.executable, "-m", MODULE, str(canary), str(values), str(malformed)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        check=False,
        timeout=60,
    )
    assert completed.returncode == 1
    assert completed.stderr == ""
    document = json.loads(completed.stdout)
    assert document["accepted"] == 2
    assert document["kinds"]["rfi"]["records_v2"] >= 2
    output = completed.stdout.lower()
    for canary_value in (*CANARIES, "CANARY-FILE", "values.json", "broken", str(tmp_path)):
        assert canary_value.lower() not in output, canary_value
    for value in ("example.invalid", "174", "999", "033000", "fp&l", "change order"):
        assert value not in output, value
