"""The redaction scanner, which is itself an acceptance control (OD-004).

Two properties are worth a test more than the regular expressions are. A finding
must never carry the text it matched, because a scanner that quoted the address
it found would put the address into the report that is meant to prove there
isn't one. And the local account name has to be discovered at runtime, because
writing it into a source file would be the same disclosure the scan exists to
catch.

Every fixture here is synthetic. The addresses and numbers are RFC 2606 and
NANP reserved forms, which are not anybody's.
"""

from __future__ import annotations

from pathlib import Path

from my_pa.infrastructure.migration import redaction

RESERVED_EMAIL = "someone@example.invalid"
RESERVED_PHONE = "555-0100"


def _rules() -> tuple[tuple[str, object], ...]:
    return redaction.patterns(home=Path("/Users/tester"))  # type: ignore[return-value]


def test_an_email_address_is_found() -> None:
    findings = redaction.scan_text("a.md", f"contact {RESERVED_EMAIL} today", redaction.patterns())
    assert [finding.pattern for finding in findings] == ["EMAIL_ADDRESS"]


def test_a_phone_number_is_found() -> None:
    findings = redaction.scan_text("a.md", f"call 212-{RESERVED_PHONE}", redaction.patterns())
    assert [finding.pattern for finding in findings] == ["PHONE_NUMBER"]


def test_a_sha_prefix_is_not_mistaken_for_a_phone_number() -> None:
    line = "base 2672898530916c3657d6e5fef47b401c219a61da tree 4368125952 bytes"
    assert redaction.scan_text("a.md", line, redaction.patterns()) == ()


def test_a_repository_relative_path_is_not_a_finding() -> None:
    line = "resolves `my_pa` to that checkout's own `src/`"
    assert redaction.scan_text("a.md", line, redaction.patterns()) == ()


def test_an_absolute_home_path_is_found() -> None:
    findings = redaction.scan_text("a.md", "PYTHONPATH=/Users/tester/repo/src", _rules())
    assert {finding.pattern for finding in findings} == {
        "HOME_DIRECTORY_PATH",
        "LOCAL_ACCOUNT_NAME",
    }


def test_the_local_account_name_comes_from_the_home_directory_it_is_given() -> None:
    line = "ran as tester"
    assert redaction.scan_text("a.md", line, _rules())[0].pattern == "LOCAL_ACCOUNT_NAME"
    other = redaction.patterns(home=Path("/Users/someone-else"))
    assert redaction.scan_text("a.md", line, other) == ()


def test_a_home_directory_name_too_short_to_be_distinctive_adds_no_rule() -> None:
    assert redaction.local_account_pattern(Path("/Users/ab")) is None
    assert "LOCAL_ACCOUNT_NAME" not in {
        name for name, _ in redaction.patterns(home=Path("/Users/ab"))
    }


def test_a_finding_never_carries_what_it_matched() -> None:
    findings = redaction.scan_text("a.md", f"mail {RESERVED_EMAIL}", redaction.patterns())
    rendered = " ".join(f"{item.path} {item.line} {item.pattern}" for item in findings)
    assert RESERVED_EMAIL not in rendered
    assert not hasattr(findings[0], "match")


def test_the_line_number_is_the_line_the_match_is_on() -> None:
    text = f"clean\nalso clean\n{RESERVED_EMAIL}\n"
    assert redaction.scan_text("a.md", text, redaction.patterns())[0].line == 3


def test_a_tree_scan_reports_paths_relative_to_the_base(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    (root / "nested").mkdir(parents=True)
    (root / "nested" / "record.md").write_text(f"mail {RESERVED_EMAIL}\n", encoding="utf-8")
    result = redaction.scan([root], base=tmp_path)
    assert [finding.path for finding in result.findings] == ["evidence/nested/record.md"]
    assert result.files_scanned == 1
    assert not result.clean


def test_a_binary_file_is_skipped_rather_than_read_as_text(tmp_path: Path) -> None:
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01" + RESERVED_EMAIL.encode())
    result = redaction.scan([tmp_path], base=tmp_path)
    assert result.files_scanned == 0
    assert result.files_skipped == 1
    assert result.clean


def test_a_clean_tree_scans_clean(tmp_path: Path) -> None:
    (tmp_path / "record.md").write_text("tables 398, rows 3263870\n", encoding="utf-8")
    assert redaction.scan([tmp_path], base=tmp_path).clean
