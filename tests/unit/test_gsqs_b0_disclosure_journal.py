"""Crash-safe append-only disclosure journal."""

from __future__ import annotations

from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs_b0_disclosure_journal import (
    DisclosureJournal,
    DisclosureState,
)


def test_started_is_durable_and_never_none(tmp_path: Path) -> None:
    journal = DisclosureJournal(tmp_path, run_id="run-1")
    attempt = journal.record_started(repetition=1, case_id="c1", raster_sha256="aa" * 32)
    fold = journal.fold()
    assert attempt in fold.unresolved_attempt_ids
    assert fold.external_model_disclosure is DisclosureState.MAY_HAVE_OCCURRED
    with pytest.raises(ValueError, match="cannot reconcile to NONE"):
        journal.record_reconciled(
            request_attempt_id=attempt,
            repetition=1,
            case_id="c1",
            raster_sha256="aa" * 32,
            disclosure_state=DisclosureState.CONFIRMED_NOT_DISCLOSED,
        )
    restarted = DisclosureJournal(tmp_path, run_id="run-1")
    with pytest.raises(ValueError, match="unresolved disclosure attempt"):
        restarted.refuse_if_unresolved()
    lines = (tmp_path / "disclosure_journal.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert "STARTED" in lines[0]


def test_transport_error_after_started_is_may_have_occurred(tmp_path: Path) -> None:
    journal = DisclosureJournal(tmp_path, run_id="run-1")
    attempt = journal.record_started(repetition=1, case_id="c1", raster_sha256="aa" * 32)
    journal.record_reconciled(
        request_attempt_id=attempt,
        repetition=1,
        case_id="c1",
        raster_sha256="aa" * 32,
        disclosure_state=DisclosureState.MAY_HAVE_OCCURRED,
        error_class="TIMEOUT",
    )
    fold = journal.fold()
    assert fold.external_model_disclosure is DisclosureState.MAY_HAVE_OCCURRED
    assert not fold.unresolved_attempt_ids


def test_http_status_is_confirmed_disclosed(tmp_path: Path) -> None:
    journal = DisclosureJournal(tmp_path, run_id="run-1")
    attempt = journal.record_started(repetition=1, case_id="c1", raster_sha256="aa" * 32)
    journal.record_reconciled(
        request_attempt_id=attempt,
        repetition=1,
        case_id="c1",
        raster_sha256="aa" * 32,
        disclosure_state=DisclosureState.CONFIRMED_DISCLOSED,
        http_status=200,
    )
    journal.record_run_event("RUN_COMPLETE", disclosure_state=DisclosureState.COMPLETE)
    fold = journal.fold()
    assert fold.external_model_disclosure is DisclosureState.COMPLETE
    assert fold.confirmed_disclosed_count == 1


def test_journal_does_not_store_forbidden_material(tmp_path: Path) -> None:
    journal = DisclosureJournal(tmp_path, run_id="run-1")
    with pytest.raises(ValueError, match="forbidden"):
        journal._append({"event_type": "X", "image_bytes": "nope"})
    body = (tmp_path / "disclosure_journal.jsonl").read_text()
    assert "image" not in body
    assert "gold" not in body
