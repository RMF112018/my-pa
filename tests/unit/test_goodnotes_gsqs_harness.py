"""B0 harness dry-run, interchange, and side-effect-free evaluation boundary."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from my_pa.application import goodnotes_gsqs as evaluator_mod
from my_pa.application import goodnotes_gsqs_harness as harness_mod
from my_pa.application.goodnotes_gsqs import (
    AUTOMATIC_PROMOTION_DISABLED,
    GATE_B_STATE,
    MEASURED_B0_NOT_YET_ESTABLISHED,
    NOTE_UNIT_V2,
    SELF_IMPROVEMENT_NOT_YET_ACTIVATED,
    AnalyzerOutput,
    CorpusPartition,
    evaluate_gsqs,
)
from my_pa.application.goodnotes_gsqs_harness import (
    INCUMBENT_ANALYZER_NAME,
    candidate_config_digest,
    dry_run_b0,
    gate_b_state_matrix,
    gold_as_output,
    harness_status,
    interchange_document,
    parse_interchange,
    planned_variance,
    require_live_b0_identities,
    score_partition,
)
from my_pa.application.goodnotes_gsqs_v2_freeze import freeze_v2_corpus
from my_pa.application.goodnotes_semantics import submit_proposal


def test_gate_b_state_ceiling() -> None:
    state = gate_b_state_matrix()
    assert state == dict(GATE_B_STATE)
    assert state["MEASURED_B0"] == MEASURED_B0_NOT_YET_ESTABLISHED
    assert state["SELF_IMPROVEMENT_EVALUATION"] == SELF_IMPROVEMENT_NOT_YET_ACTIVATED
    assert state["AUTOMATIC_PROMOTION"] == AUTOMATIC_PROMOTION_DISABLED
    assert state["FIXED_LABELED_CORPUS"] == "READY_FOR_OPERATOR_REVIEW"
    assert state["INDEPENDENT_EVALUATOR"] == "VALIDATED"
    assert state["B0_HARNESS"] == "READY"
    assert state["CONTROLLED_HANDWRITING_CORPUS"] == "READY_FOR_REVIEW"
    assert state["GSQS_V1_B0_DISPOSITION"] == "REJECT_FOR_B0"
    status = harness_status()
    assert status.ready is True
    assert status.measured_b0 == MEASURED_B0_NOT_YET_ESTABLISHED
    assert status.incumbent_name == INCUMBENT_ANALYZER_NAME


def test_dry_run_refuses_to_fake_incumbent_and_does_not_call_propose() -> None:
    cases, manifest = freeze_v2_corpus()
    with pytest.raises(ValueError, match="not authorized"):
        dry_run_b0(
            cases,
            manifest,
            analyzer_name=INCUMBENT_ANALYZER_NAME,
            analyzer_version="sit-1.0",
        )
    records, plan = dry_run_b0(cases, manifest, repetitions=3)
    assert len(records) == 3
    assert all(item.measurement_valid for item in records)
    assert all(item.analyzer_name != INCUMBENT_ANALYZER_NAME for item in records)
    assert plan.mean_gsqs is not None
    assert plan.stdev_gsqs == 0.0
    assert "empirical" in plan.threshold_policy
    first = json.dumps(records[0].canonical_dict(), sort_keys=True)
    second = json.dumps(records[0].canonical_dict(), sort_keys=True)
    assert first == second
    assert "submit_proposal" in submit_proposal.__name__
    assert planned_variance().mean_gsqs is None
    assert "submit_proposal" not in evaluator_mod.__dict__
    assert "submit_proposal" not in harness_mod.__dict__


def test_interchange_round_trip_and_gold_replay() -> None:
    cases, _manifest = freeze_v2_corpus()
    case = next(item for item in cases if item.scoreable)
    output = gold_as_output(case, analyzer_name="deterministic-gold-replay", analyzer_version="1")
    document = interchange_document(case, output)
    parsed = parse_interchange(document)
    assert parsed.case_id == case.case_id
    assert parsed.schema_version == output.schema_version
    assert parsed.corpus_version == case.corpus_version
    assert parsed.content_sha256 == case.content_sha256
    assert len(parsed.segments) == len(output.segments)
    with pytest.raises(ValueError, match="unsupported"):
        parse_interchange({**document, "schema_version": "other"})


def _valid_interchange() -> dict[str, object]:
    cases, _manifest = freeze_v2_corpus()
    case = next(item for item in cases if item.scoreable)
    output = gold_as_output(case, analyzer_name="deterministic-gold-replay", analyzer_version="1")
    return interchange_document(case, output)


def test_malformed_interchange_fails_closed() -> None:
    document = _valid_interchange()
    geometry = {"x_min": 0.1, "y_min": 0.2, "width": 0.3, "height": 0.1}
    note = {
        "kind": "NOTE_UNIT",
        "geometry": geometry,
        "transcription": "synthetic follow up monday",
        "transcription_status": "CLEAR",
        "primary_class": "GENERAL",
        "candidate_tags": [],
        "ranked_candidates": [],
    }

    def parse(overrides: dict[str, object]) -> None:
        parse_interchange({**document, **overrides})

    with pytest.raises(ValueError, match="malformed segments"):
        parse({"segments": ["not-an-object"]})
    with pytest.raises(ValueError, match="malformed segments"):
        parse({"segments": []})
    with pytest.raises(ValueError, match="malformed segments"):
        parse({"segments": [note] * 51})
    with pytest.raises(ValueError, match="malformed interchange: missing case_id"):
        parse_interchange({k: v for k, v in document.items() if k != "case_id"})
    with pytest.raises(ValueError, match="malformed interchange: case_id"):
        parse({"case_id": 1})
    with pytest.raises(ValueError, match="malformed proposal_schema_version"):
        parse({"proposal_schema_version": "note-unit.v1"})
    with pytest.raises(ValueError, match="malformed geometry"):
        parse({"segments": [{**note, "geometry": {"x_min": "bad"}}]})
    with pytest.raises(ValueError, match="malformed geometry"):
        parse(
            {
                "segments": [
                    {**note, "geometry": {**geometry, "extra": 0.1}},
                ]
            }
        )
    with pytest.raises(ValueError, match="malformed geometry"):
        parse({"segments": [{**note, "geometry": {**geometry, "width": True}}]})
    with pytest.raises(ValueError, match="malformed geometry"):
        parse({"segments": [{**note, "geometry": {**geometry, "width": 0}}]})
    with pytest.raises(ValueError, match="malformed ranked_candidates"):
        parse({"segments": [{**note, "ranked_candidates": ["x"]}]})
    with pytest.raises(ValueError, match="malformed ranked_candidates"):
        parse({"segments": [{**note, "ranked_candidates": [{"rank": True, "candidate": "a"}]}]})
    with pytest.raises(ValueError, match="malformed ranked_candidates"):
        parse(
            {
                "segments": [
                    {
                        **note,
                        "ranked_candidates": [
                            {"rank": 1, "candidate": "a"},
                            {"rank": 1, "candidate": "b"},
                        ],
                    }
                ]
            }
        )
    with pytest.raises(ValueError, match="malformed candidate_tags"):
        parse({"segments": [{**note, "candidate_tags": [123]}]})
    with pytest.raises(ValueError, match="malformed candidate_tags"):
        parse({"segments": [{**note, "candidate_tags": ["a", "a"]}]})
    with pytest.raises(ValueError, match="malformed segments"):
        parse({"segments": [{**note, "transcription_status": "LOUD"}]})
    with pytest.raises(ValueError, match="malformed transcription"):
        parse({"segments": [{**note, "transcription": "", "transcription_status": "CLEAR"}]})
    with pytest.raises(ValueError, match="malformed transcription"):
        parse({"segments": [{**note, "transcription": 1}]})
    with pytest.raises(ValueError, match="malformed confidence"):
        parse({"segments": [{**note, "confidence": "high"}]})
    with pytest.raises(ValueError, match="malformed confidence"):
        parse({"segments": [{**note, "confidence": {"segmentation": True}}]})
    with pytest.raises(ValueError, match="malformed confidence"):
        parse({"segments": [{**note, "confidence": {"segmentation": 1.2}}]})
    with pytest.raises(ValueError, match="malformed confidence"):
        parse({"segments": [{**note, "confidence": {"mystery": 0.1}}]})
    with pytest.raises(ValueError, match="malformed segments"):
        parse({"segments": [{**note, "crop_sha256": "AB" * 32}]})
    with pytest.raises(ValueError, match="malformed segments"):
        parse(
            {
                "segments": [
                    {
                        "kind": "SOURCE_CONTEXT",
                        "geometry": geometry,
                        "transcription": "printed title",
                        "transcription_status": "CLEAR",
                    }
                ]
            }
        )
    with pytest.raises(ValueError, match="malformed segments"):
        parse({"segments": [{**note, "note_id": "note_hidden"}]})

    context = {
        "kind": "SOURCE_CONTEXT",
        "geometry": geometry,
        "transcription": "printed title",
    }
    parsed = parse_interchange({**document, "segments": [context]})
    assert parsed.segments[0].kind.value == "SOURCE_CONTEXT"
    crop = "ab" * 32
    cropped = parse_interchange({**document, "segments": [{**note, "crop_sha256": crop}]})
    assert cropped.segments[0].crop_sha256 == crop


def test_harness_invalidates_analyzer_corpus_version_mismatch() -> None:
    cases, manifest = freeze_v2_corpus()
    selected = [item for item in cases if item.partition is CorpusPartition.B and item.scoreable]
    outputs = tuple(
        AnalyzerOutput(
            case_id=item.case_id,
            schema_version=NOTE_UNIT_V2,
            analyzer_name="deterministic-gold-replay",
            analyzer_version="harness-dry-run",
            segments=gold_as_output(
                item, analyzer_name="deterministic-gold-replay", analyzer_version="1"
            ).segments,
            corpus_version="other",
        )
        for item in selected
    )
    result, record = score_partition(
        cases,
        outputs,
        partition=CorpusPartition.B,
        manifest=manifest,
        analyzer_name="deterministic-gold-replay",
        analyzer_version="harness-dry-run",
        run_repetition=1,
    )
    assert result.measurement_valid is False
    assert record.measurement_valid is False


def test_content_digest_binding_fails_closed() -> None:
    cases, manifest = freeze_v2_corpus()
    selected = [item for item in cases if item.partition is CorpusPartition.B and item.scoreable]
    first, second = selected[0], selected[1]
    good = gold_as_output(first, analyzer_name="x", analyzer_version="1")
    document = interchange_document(first, good)
    parsed = parse_interchange(document)
    gold = ((first.case_id, first.regions),)
    expected = {first.case_id: first.content_sha256}
    ok = evaluate_gsqs(gold, (parsed,), expected_content_sha256=expected)
    assert ok.measurement_valid is True
    with pytest.raises(ValueError, match="malformed content_sha256"):
        parse_interchange({k: v for k, v in document.items() if k != "content_sha256"})
    with pytest.raises(ValueError, match="malformed content_sha256"):
        parse_interchange({**document, "content_sha256": first.content_sha256.upper()})
    with pytest.raises(ValueError, match="malformed content_sha256"):
        parse_interchange({**document, "content_sha256": "not-a-digest"})
    wrong_digest = replace(parsed, content_sha256=second.content_sha256)
    stale = evaluate_gsqs(gold, (wrong_digest,), expected_content_sha256=expected)
    assert stale.measurement_valid is False
    assert stale.invalid_reason == "analyzer/content digest mismatch"
    wrong_case = replace(parsed, case_id=second.case_id)
    wrong_case_result = evaluate_gsqs(
        ((second.case_id, second.regions),),
        (wrong_case,),
        expected_content_sha256={second.case_id: second.content_sha256},
    )
    assert wrong_case_result.measurement_valid is False
    pair_gold = ((first.case_id, first.regions), (second.case_id, second.regions))
    swapped = (
        replace(
            gold_as_output(first, analyzer_name="x", analyzer_version="1"), case_id=second.case_id
        ),
        replace(
            gold_as_output(second, analyzer_name="x", analyzer_version="1"), case_id=first.case_id
        ),
    )
    swapped_result = evaluate_gsqs(
        pair_gold,
        swapped,
        expected_content_sha256={
            first.case_id: first.content_sha256,
            second.case_id: second.content_sha256,
        },
    )
    assert swapped_result.measurement_valid is False
    mismatched = (
        replace(
            gold_as_output(first, analyzer_name="x", analyzer_version="1"),
            content_sha256=second.content_sha256,
        ),
        gold_as_output(second, analyzer_name="x", analyzer_version="1"),
    )
    mismatch = evaluate_gsqs(
        pair_gold,
        mismatched,
        expected_content_sha256={
            first.case_id: first.content_sha256,
            second.case_id: second.content_sha256,
        },
    )
    assert mismatch.measurement_valid is False
    outputs = tuple(
        gold_as_output(item, analyzer_name="x", analyzer_version="1") for item in selected
    )
    _, record = score_partition(
        cases,
        outputs,
        partition=CorpusPartition.B,
        manifest=manifest,
        analyzer_name="x",
        analyzer_version="1",
        run_repetition=1,
        repository_commit="aa" * 20,
        repository_tree="bb" * 20,
    )
    assert record.measurement_valid is True
    assert record.repository_commit == "aa" * 20
    assert record.canonical_dict()["repository_tree"] == "bb" * 20


def test_candidate_config_digest_binds_model_and_prompt() -> None:
    identity = "ee" * 32
    base = {
        "analyzer_name": "local",
        "analyzer_version": "1",
        "model_identity": "model-a",
        "prompt_config_identity": "prompt-a",
        "corpus_manifest_digest": "cc" * 32,
        "partition": "B",
        "evaluator_behavior_identity": identity,
    }
    first = candidate_config_digest(**base)
    assert first == candidate_config_digest(**base)
    assert candidate_config_digest(**{**base, "model_identity": "model-b"}) != first
    assert candidate_config_digest(**{**base, "prompt_config_identity": "prompt-b"}) != first
    assert candidate_config_digest(**{**base, "analyzer_version": "2"}) != first
    assert candidate_config_digest(**{**base, "corpus_manifest_digest": "dd" * 32}) != first
    assert candidate_config_digest(**{**base, "evaluator_behavior_identity": "ff" * 32}) != first
    none_id = candidate_config_digest(**{**base, "model_identity": None})
    assert none_id != first
    cases, manifest = freeze_v2_corpus()
    selected = [item for item in cases if item.partition is CorpusPartition.B and item.scoreable]
    outputs = tuple(
        gold_as_output(item, analyzer_name="local", analyzer_version="1") for item in selected
    )
    stamp = datetime(2026, 8, 20, tzinfo=UTC)
    _, record_a = score_partition(
        cases,
        outputs,
        partition=CorpusPartition.B,
        manifest=manifest,
        analyzer_name="local",
        analyzer_version="1",
        run_repetition=1,
        measured_at=stamp,
        model_identity="model-a",
        prompt_config_identity="prompt-a",
    )
    _, record_b = score_partition(
        cases,
        outputs,
        partition=CorpusPartition.B,
        manifest=manifest,
        analyzer_name="local",
        analyzer_version="1",
        run_repetition=2,
        measured_at=stamp.replace(minute=1),
        model_identity="model-a",
        prompt_config_identity="prompt-a",
    )
    assert record_a.candidate_config_digest == record_b.candidate_config_digest
    _, record_c = score_partition(
        cases,
        outputs,
        partition=CorpusPartition.B,
        manifest=manifest,
        analyzer_name="local",
        analyzer_version="1",
        run_repetition=1,
        measured_at=stamp,
        model_identity="model-b",
        prompt_config_identity="prompt-a",
    )
    assert record_c.candidate_config_digest != record_a.candidate_config_digest
    with pytest.raises(ValueError, match="model_identity"):
        require_live_b0_identities(
            analyzer_name=INCUMBENT_ANALYZER_NAME,
            model_identity=None,
            prompt_config_identity="prompt-a",
        )
    with pytest.raises(ValueError, match="not authorized"):
        dry_run_b0(
            cases,
            manifest,
            analyzer_name=INCUMBENT_ANALYZER_NAME,
            analyzer_version="sit-1.0",
        )
