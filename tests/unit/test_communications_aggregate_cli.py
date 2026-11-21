"""The aggregate CLI: aggregate-only output, exit status, and a canary no-leak proof."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from my_pa.infrastructure.communications.aggregate_cli import main, summarize_files
from tests.fixtures.communications_evidence import synthetic as s

SRC = Path(__file__).resolve().parents[2] / "src"
MODULE = "my_pa.infrastructure.communications.aggregate_cli"

CANARIES = (
    "CANARY-SUBJECT-xyz",
    "canary@example.invalid",
    "CANARY-PROVIDER-ID",
    "CANARY-IMID",
    "CANARY-CONVERSATION",
    "CANARY-BODY",
    "CANARY-DISPLAY",
    "CANARY-KEY",
    "CANARY-FOLDER",
    "CANARY-SOURCE",
    "CANARY-RULE",
    "Canary/Zone",
    "CANARY-MAILBOX",
    "CANARY-DERIVED",
)


def canary_publication() -> dict[str, Any]:
    """Canaries in every string field a record or envelope can carry."""

    def record(
        n: int, *, imid: str | None = "", selected: str = "2026-11-17T12:00:00Z"
    ) -> dict[str, Any]:
        r = s.message(
            n,
            imid=f"<CANARY-IMID-{n}@example.invalid>" if imid == "" else imid,
            selected=selected,
            provider_id=f"CANARY-PROVIDER-ID-{n}",
            sender="canary@example.invalid",
            subject="CANARY-SUBJECT-xyz RFI 174 GMP",
            content="<p>CANARY-BODY RFI 174</p><script>CANARY-BODY</script>",
        )
        r["mailbox_ref"] = "CANARY-MAILBOX"
        r["dedup_key"] = "CANARY-KEY"
        r["conversation_id"] = "CANARY-CONVERSATION"
        r["from"]["value"]["display_name"] = "CANARY-DISPLAY"
        r["source_folder"]["key"] = "CANARY-FOLDER"
        r["CANARY-KEY"] = "CANARY-BODY"
        derived = "CANARY-DERIVED text"
        r["body_derived_plain_text"] = {"derived": True, "sha256": s.sha(derived), "text": derived}
        return r

    good = record(1)
    withheld = s.richen(record(2), withheld=True)
    bad = record(3)
    bad["body"]["sha256"] = s.sha("CANARY-BODY other")
    conflict = copy.deepcopy(record(4))
    conflict["internet_message_id"] = "<CANARY-IMID-1@example.invalid>"
    conflict["from"]["value"]["address_normalized"] = "canary-other@example.invalid"
    no_imid = record(5, imid=None)
    outside = record(6, selected="2026-11-19T00:00:00Z")
    document = s.publication(
        [good, withheld, bad, conflict, no_imid, outside, "CANARY-SUBJECT-xyz"],
        s.window("2026-11-17T05:00:00Z", "2026-11-18T04:59:59Z", 24, "CANARY-RULE"),
        rich=True,
    )
    document["mailbox_ref"] = "CANARY-MAILBOX"
    document["window"]["tz"] = "Canary/Zone"
    document["window"]["semantics"] = "CANARY-RULE"
    document["coverage"]["sources"][0]["key"] = "CANARY-SOURCE"
    document["CANARY-KEY"] = {"CANARY-KEY": "CANARY-BODY"}
    return document


def write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def run_cli(*paths: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run(  # noqa: S603 - fixed interpreter and module, synthetic paths
        [sys.executable, "-m", MODULE, *map(str, paths)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )


def test_the_cli_output_contains_no_canary(tmp_path: Path) -> None:
    good = write(tmp_path, "canary.json", s.encode(canary_publication()))
    malformed = write(tmp_path, "broken.json", b'{"subject": "CANARY-SUBJECT-xyz", "x": [')
    completed = run_cli(good, malformed)
    assert completed.returncode == 1  # the malformed file is rejected
    assert completed.stderr == ""
    document = json.loads(completed.stdout)
    report = document["files"][0]
    assert report["status"] == "accepted"
    records = report["records"]
    # The canary publication exercised every path that could carry content.
    assert records["by_classification"]["quarantined"] >= 3
    assert records["by_classification"]["out_of_window"] == 1
    assert records["by_body_state"]["withheld"] == 1
    assert records["identifier_kind_messages"]["rfi"] >= 1
    assert report["window"]["tz"] is None
    assert report["window"]["rule"] == "other"
    assert report["coverage"]["sources"][0]["key_kind"] == "other"
    assert document["files"][1]["rejection"] == "malformed_json"
    output = (completed.stdout + completed.stderr).lower()
    for canary in CANARIES:
        assert canary.lower() not in output, canary
    assert "example.invalid" not in output
    assert "174" not in output


def test_all_fixtures_accepted_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    paths = [s.HERE / name for name in s.COMMITTED]
    assert main([str(p) for p in paths]) == 0
    document = json.loads(capsys.readouterr().out)
    assert [f["file"] for f in document["files"]] == list(s.COMMITTED)
    assert document["summary"]["accepted"] == 3
    assert document["summary"]["inbox_sent_pairs"] == 1
    gap = document["summary"]["coverage"]["gaps"][0]
    assert gap == {
        "start_utc": "2026-11-16T07:00:00Z",
        "end_utc": "2026-11-17T05:00:00Z",
        "seconds": 22 * 3600,
    }


def test_the_per_file_report_carries_the_aggregates() -> None:
    document, all_accepted = summarize_files([s.HERE / "friday_publication.json"])
    assert all_accepted
    (report,) = document["files"]  # type: ignore[misc]
    assert report["dialect"] == "lean"
    assert report["schema_version"] == "2.0.0"
    assert report["window"]["declared_hours"] == 24.0
    assert report["window"]["actual_hours"] == 33.2
    assert report["diagnostics"]["code_counts"] == {"window_hours_mismatch": 1}
    data = (s.HERE / "friday_publication.json").read_bytes()
    assert report["bytes"] == len(data)


def test_an_unreadable_file_is_a_rejection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path / "absent.json")]) == 1
    document = json.loads(capsys.readouterr().out)
    assert document["files"][0] == {
        "file": "absent.json",
        "status": "rejected",
        "rejection": "file_unreadable",
    }


def test_no_arguments_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main([])
    assert raised.value.code == 2
    assert capsys.readouterr().out == ""
