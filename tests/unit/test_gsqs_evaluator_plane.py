"""Evaluator-plane loader reuses case_digest_payload. No new gold schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs_corpus import (
    dump_evaluator_plane_cases,
    load_evaluator_plane_cases,
)
from my_pa.application.goodnotes_gsqs_live_b0 import validate_evaluator_plane
from tests.unit.test_goodnotes_gsqs_live_b0 import _build_fixture


def test_roundtrip_synthetic_evaluator_cases(tmp_path: Path) -> None:
    cases, _manifest, census, _config = _build_fixture()
    path = tmp_path / "evaluator.json"
    path.write_text(json.dumps(dump_evaluator_plane_cases(cases)), encoding="utf-8")
    loaded = load_evaluator_plane_cases(path)
    assert [item.case_id for item in loaded] == [item.case_id for item in cases]
    assert all(item.page_bytes == b"" for item in loaded)
    validate_evaluator_plane(loaded, census)


def test_missing_and_wrong_cases_fail_closed(tmp_path: Path) -> None:
    cases, _manifest, census, _config = _build_fixture()
    with pytest.raises(ValueError, match="evaluator corpus is missing"):
        load_evaluator_plane_cases(tmp_path / "absent.json")
    path = tmp_path / "evaluator.json"
    path.write_text(json.dumps({"schema_version": "nope", "cases": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="wrong evaluator corpus schema"):
        load_evaluator_plane_cases(path)
    path.write_text(json.dumps(dump_evaluator_plane_cases(cases[:1])), encoding="utf-8")
    loaded = load_evaluator_plane_cases(path)
    with pytest.raises(ValueError, match="evaluator cases do not match"):
        validate_evaluator_plane(loaded, census)
    payload = dump_evaluator_plane_cases(cases)
    payload["corpus_version"] = "wrong-version"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="wrong corpus version"):
        load_evaluator_plane_cases(path)
    mismatched = dump_evaluator_plane_cases(cases)
    mismatched["cases"][0]["content_sha256"] = "0" * 64
    path.write_text(json.dumps(mismatched), encoding="utf-8")
    loaded = load_evaluator_plane_cases(path)
    with pytest.raises(ValueError, match="evaluator raster binding mismatch"):
        validate_evaluator_plane(loaded, census)
