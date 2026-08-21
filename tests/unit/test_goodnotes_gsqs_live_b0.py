"""Governed live-B0 runner: preflight, authorization, adapter boundary, aggregation."""

from __future__ import annotations

import copy
import inspect
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs import (
    AUTOMATIC_PROMOTION_DISABLED,
    GATE_B_STATE,
    MEASURED_B0_NOT_YET_ESTABLISHED,
    SELF_IMPROVEMENT_NOT_YET_ACTIVATED,
    CorpusPartition,
    evaluator_code_identity,
)
from my_pa.application.goodnotes_gsqs_corpus import CorpusCase, CorpusManifest
from my_pa.application.goodnotes_gsqs_harness import (
    INCUMBENT_ANALYZER_NAME,
    INCUMBENT_ANALYZER_VERSION,
    dry_run_b0,
    gold_as_output,
    interchange_document,
    score_partition,
)
from my_pa.application.goodnotes_gsqs_hw_corpus import load_public_catalog
from my_pa.application.goodnotes_gsqs_live_b0 import (
    APPROVED_COMBINED_IDENTITY,
    APPROVED_MANIFEST_DIGEST,
    EXECUTE_MEASURED_B0,
    EXPECTED_SCOREABLE_B,
    AnalyzerCaseInput,
    B0Census,
    B0CensusMember,
    B0RunState,
    ExecutionAuthorization,
    FrozenAnalyzerConfig,
    RecordingFakeAdapter,
    RepositoryIdentity,
    UnboundIncumbentAdapter,
    admit_repetition_outputs,
    aggregate_b0_measurements,
    analyzer_request_payload,
    authorization_from_mapping,
    catalog_path,
    execute_measured_b0,
    frozen_incumbent_config,
    partition_b_census,
    preflight,
    prompt_config_identity,
    write_public_evidence,
)
from my_pa.application.goodnotes_gsqs_v2_freeze import freeze_v2_corpus

COMMIT = "aa" * 20
TREE = "bb" * 20
MODEL = "chatllm-model-fixture-not-live"
PROMPT_ID_OVERRIDE = "prompt-fixture"


def _clean_repo() -> RepositoryIdentity:
    return RepositoryIdentity(commit=COMMIT, tree=TREE, dirty=False)


def _catalog() -> dict[str, object]:
    return load_public_catalog(catalog_path())


def _auth(**overrides: object) -> ExecutionAuthorization:
    payload: dict[str, object] = {
        "analyzer_name": INCUMBENT_ANALYZER_NAME,
        "analyzer_version": INCUMBENT_ANALYZER_VERSION,
        "authorization_id": "SYNTHETIC-AUTH-FIXTURE",
        "combined_identity": APPROVED_COMBINED_IDENTITY,
        "corpus_manifest_digest": APPROVED_MANIFEST_DIGEST,
        "corpus_version": "gsqs-hw-combined-v1",
        "decided_at": "2026-08-21T00:00:00Z",
        "evaluator_behavior_identity": evaluator_code_identity(),
        "expected_case_count": EXPECTED_SCOREABLE_B,
        "model_identity": MODEL,
        "operation": EXECUTE_MEASURED_B0,
        "operator_evidence_id": "synthetic-fixture",
        "partition": "B",
        "prohibit_automatic_promotion": True,
        "prohibit_corpus_c": True,
        "prohibit_deployment": True,
        "prohibit_self_improvement": True,
        "prompt_config_identity": prompt_config_identity(),
        "repetitions": 3,
        "repository_commit": COMMIT,
        "repository_tree": TREE,
    }
    payload.update(overrides)
    return authorization_from_mapping(payload)


def _document(case: CorpusCase, *, prompt: str) -> dict[str, object]:
    output = gold_as_output(
        case, analyzer_name=INCUMBENT_ANALYZER_NAME, analyzer_version=INCUMBENT_ANALYZER_VERSION
    )
    document = interchange_document(case, output)
    document["model_identity"] = MODEL
    document["prompt_config_identity"] = prompt
    return document


def _build_fixture() -> tuple[
    tuple[CorpusCase, ...], CorpusManifest, B0Census, FrozenAnalyzerConfig
]:
    cases, manifest = freeze_v2_corpus()
    selected = tuple(
        item for item in cases if item.partition is CorpusPartition.B and item.scoreable
    )[:2]
    members = tuple(
        B0CensusMember(
            case_id=item.case_id,
            raster_sha256=item.content_sha256,
            case_digest="cd" + item.case_id[-8:].ljust(8, "0"),
            file_sha256=item.content_sha256,
        )
        for item in selected
    )
    census = B0Census(
        corpus_version=manifest.corpus_version,
        manifest_digest=manifest.manifest_digest,
        combined_identity="cc" * 32,
        partition="B",
        members=members,
        census_digest="dd" * 32,
    )
    config = replace(
        frozen_incumbent_config(model_identity=MODEL), prompt_config_identity=PROMPT_ID_OVERRIDE
    )
    return selected, manifest, census, config


def _fixture_auth(
    census: B0Census, manifest: CorpusManifest, config: FrozenAnalyzerConfig
) -> ExecutionAuthorization:
    return _auth(
        combined_identity=census.combined_identity,
        corpus_manifest_digest=manifest.manifest_digest,
        corpus_version=census.corpus_version,
        expected_case_count=len(census.members),
        model_identity=MODEL,
        prompt_config_identity=config.prompt_config_identity,
    )


def test_preflight_accepts_approved_partition_b_census() -> None:
    report = preflight(catalog=_catalog(), repository=_clean_repo())
    assert report.go is True
    assert report.state is B0RunState.PREPARED
    assert report.scoreable_b == EXPECTED_SCOREABLE_B
    assert report.manifest_digest == APPROVED_MANIFEST_DIGEST
    assert report.combined_identity == APPROVED_COMBINED_IDENTITY
    assert report.disclosure_would_occur is False
    census = partition_b_census(_catalog())
    assert len({item.case_id for item in census.members}) == EXPECTED_SCOREABLE_B
    catalog = _catalog()
    admitted_ac = [
        case
        for case in catalog["cases"]  # type: ignore[index]
        if case["partition"] in {"A", "C"} and not case["excluded"]
    ]
    assert admitted_ac
    assert {item.case_id for item in census.members}.isdisjoint(
        {case["case_id"] for case in admitted_ac}
    )


def test_preflight_rejects_dirty_repository_and_identity_mismatches() -> None:
    dirty = preflight(catalog=_catalog(), repository=RepositoryIdentity(COMMIT, TREE, dirty=True))
    assert dirty.go is False
    assert "dirty" in dirty.reasons[0]
    digest = preflight(
        catalog=_catalog(), repository=_clean_repo(), expected_manifest_digest="ff" * 32
    )
    assert "corpus manifest digest mismatch" in digest.reasons
    combined = preflight(
        catalog=_catalog(), repository=_clean_repo(), expected_combined_identity="ee" * 32
    )
    assert "combined identity mismatch" in combined.reasons
    auth = _auth(evaluator_behavior_identity="00" * 32)
    evaluator = preflight(catalog=_catalog(), repository=_clean_repo(), authorization=auth)
    assert "wrong evaluator identity" in evaluator.reasons


def test_authorization_accepts_matching_fixture_and_rejects_drift() -> None:
    report = preflight(catalog=_catalog(), repository=_clean_repo(), authorization=_auth())
    assert report.go is True
    cases: list[tuple[str, object, str | None]] = [
        ("operation", "TUNE_MODEL", "wrong operation"),
        ("repository_commit", "cc" * 20, "wrong commit"),
        ("repository_tree", "dd" * 20, "wrong tree"),
        ("corpus_manifest_digest", "11" * 32, "wrong corpus digest"),
        ("combined_identity", "22" * 32, "wrong combined identity"),
        ("partition", "C", "wrong partition"),
        ("analyzer_name", "other-analyzer", "wrong analyzer"),
        ("model_identity", "", "authorization missing model_identity"),
        ("prompt_config_identity", "other-prompt", "wrong prompt identity"),
        ("repetitions", 2, "wrong repetition scope"),
        ("prohibit_corpus_c", False, "prohibition"),
        ("prohibit_self_improvement", False, "prohibition"),
        ("prohibit_automatic_promotion", False, "prohibition"),
        ("prohibit_deployment", False, "prohibition"),
    ]
    for key, value, match in cases:
        if match is None or (match is not None and match.startswith("authorization missing")):
            if match is None:
                with pytest.raises(ValueError, match="live B0 requires explicit"):
                    _auth(**{key: value})
            else:
                with pytest.raises(ValueError, match="authorization missing"):
                    _auth(**{key: value})
            continue
        if match == "prohibition":
            with pytest.raises(ValueError, match="required prohibition"):
                _auth(**{key: value})
            continue
        auth = _auth(**{key: value})
        failed = preflight(catalog=_catalog(), repository=_clean_repo(), authorization=auth)
        assert failed.go is False, key
        assert any(match in reason for reason in failed.reasons), (key, failed.reasons)


def test_execute_requires_authorization_and_cannot_enable_c() -> None:
    import apps.cli.gsqs_b0 as cli

    assert (
        cli.main(
            [
                "execute",
                "--model-identity",
                MODEL,
                "--prompt-config",
                "x",
                "--repetitions",
                "3",
            ]
        )
        == 1
    )
    auth = _auth(partition="C")
    report = preflight(catalog=_catalog(), repository=_clean_repo(), authorization=auth)
    assert report.go is False
    assert report.disclosure_would_occur is False


def test_analyzer_plane_never_receives_gold_or_other_pages() -> None:
    cases, manifest, census, config = _build_fixture()
    documents = {
        case.case_id: _document(case, prompt=config.prompt_config_identity) for case in cases
    }
    adapter = RecordingFakeAdapter(documents)
    loaded: list[str] = []

    def loader(case_id: str) -> bytes:
        loaded.append(case_id)
        return case_id.encode()

    records, state = execute_measured_b0(
        authorization=_fixture_auth(census, manifest, config),
        census=census,
        evaluator_cases=cases,
        manifest=manifest,
        adapter=adapter,
        config=config,
        repository=_clean_repo(),
        image_loader=loader,
        measured_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert state is B0RunState.COMPLETE
    assert len(records) == 3
    assert [item.case_id for item in adapter.seen] == [
        member.case_id for member in census.members
    ] * 3
    for request in adapter.seen:
        payload = analyzer_request_payload(request, config)
        assert not {"gold", "regions", "label_sha256"} & set(payload)
        gold_case = next(item for item in cases if item.case_id == request.case_id)
        assert gold_case.regions[0].transcription not in json.dumps(payload)
        assert request.image_bytes == request.case_id.encode()
    assert loaded == [member.case_id for member in census.members] * 3


def test_admission_rejects_malformed_mixed_duplicate_missing_and_extra() -> None:
    cases, _manifest, census, config = _build_fixture()
    first, second = cases
    valid = [
        _document(first, prompt=config.prompt_config_identity),
        _document(second, prompt=config.prompt_config_identity),
    ]
    malformed = dict(valid[0])
    malformed["schema_version"] = "nope"
    with pytest.raises(ValueError, match="unsupported analyzer interchange schema"):
        admit_repetition_outputs([malformed, valid[1]], census=census, config=config)
    mixed = dict(valid[1])
    mixed["analyzer_name"] = "other"
    with pytest.raises(ValueError, match="analyzer name mismatch"):
        admit_repetition_outputs([valid[0], mixed], census=census, config=config)
    with pytest.raises(ValueError, match="duplicate analyzer output"):
        admit_repetition_outputs([valid[0], valid[0]], census=census, config=config)
    extra = dict(valid[1])
    extra["case_id"] = "not-in-census"
    with pytest.raises(ValueError, match="unknown analyzer output case"):
        admit_repetition_outputs([valid[0], extra], census=census, config=config)
    with pytest.raises(ValueError, match="cover the Partition B census exactly"):
        admit_repetition_outputs([valid[0]], census=census, config=config)


def test_scoring_uses_score_partition_and_binds_identities() -> None:
    cases, manifest, census, config = _build_fixture()
    documents = {
        case.case_id: _document(case, prompt=config.prompt_config_identity) for case in cases
    }
    records, _state = execute_measured_b0(
        authorization=_fixture_auth(census, manifest, config),
        census=census,
        evaluator_cases=cases,
        manifest=manifest,
        adapter=RecordingFakeAdapter(documents),
        config=config,
        repository=_clean_repo(),
        measured_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert "score_partition(" in inspect.getsource(execute_measured_b0)
    assert all(item.analyzer_name == INCUMBENT_ANALYZER_NAME for item in records)
    assert all(item.model_identity == MODEL for item in records)
    assert all(item.prompt_config_identity == config.prompt_config_identity for item in records)
    assert all(item.repository_commit == COMMIT for item in records)
    assert all(item.repository_tree == TREE for item in records)
    dry_run_b0(cases, manifest, repetitions=3)
    with pytest.raises(ValueError, match="not authorized"):
        dry_run_b0(
            cases,
            manifest,
            analyzer_name=INCUMBENT_ANALYZER_NAME,
            analyzer_version=INCUMBENT_ANALYZER_VERSION,
        )
    outputs = admit_repetition_outputs(
        [documents[case.case_id] for case in cases], census=census, config=config
    )
    _result, record = score_partition(
        cases,
        outputs,
        partition=CorpusPartition.B,
        manifest=manifest,
        analyzer_name=INCUMBENT_ANALYZER_NAME,
        analyzer_version=INCUMBENT_ANALYZER_VERSION,
        run_repetition=1,
        model_identity=MODEL,
        prompt_config_identity=config.prompt_config_identity,
        repository_commit=COMMIT,
        repository_tree=TREE,
    )
    assert record.measurement_valid is True
    assert records[0].candidate_config_digest == record.candidate_config_digest


def test_repetitions_reuse_census_and_reject_config_drift() -> None:
    cases, manifest, census, config = _build_fixture()
    documents = {
        case.case_id: _document(case, prompt=config.prompt_config_identity) for case in cases
    }
    adapter = RecordingFakeAdapter(documents)
    auth = _fixture_auth(census, manifest, config)
    execute_measured_b0(
        authorization=auth,
        census=census,
        evaluator_cases=cases,
        manifest=manifest,
        adapter=adapter,
        config=config,
        repository=_clean_repo(),
        measured_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    expected = [member.case_id for member in census.members]
    assert [item.case_id for item in adapter.seen[:2]] == expected
    assert [item.case_id for item in adapter.seen[2:4]] == expected
    assert [item.case_id for item in adapter.seen[4:6]] == expected

    class ModelDrift(RecordingFakeAdapter):
        def analyze(
            self, case: AnalyzerCaseInput, config: FrozenAnalyzerConfig
        ) -> dict[str, object]:
            document = super().analyze(case, config)
            if len(self.seen) > 2:
                document["model_identity"] = "drifted-model"
            return document

    with pytest.raises(ValueError, match="model identity mismatch"):
        execute_measured_b0(
            authorization=auth,
            census=census,
            evaluator_cases=cases,
            manifest=manifest,
            adapter=ModelDrift(documents),
            config=config,
            repository=_clean_repo(),
        )

    class PromptDrift(RecordingFakeAdapter):
        def analyze(
            self, case: AnalyzerCaseInput, config: FrozenAnalyzerConfig
        ) -> dict[str, object]:
            document = super().analyze(case, config)
            if len(self.seen) > 2:
                document["prompt_config_identity"] = "drifted-prompt"
            return document

    with pytest.raises(ValueError, match="prompt identity mismatch"):
        execute_measured_b0(
            authorization=auth,
            census=census,
            evaluator_cases=cases,
            manifest=manifest,
            adapter=PromptDrift(documents),
            config=config,
            repository=_clean_repo(),
        )
    with pytest.raises(ValueError, match="dirty"):
        execute_measured_b0(
            authorization=auth,
            census=census,
            evaluator_cases=cases,
            manifest=manifest,
            adapter=adapter,
            config=config,
            repository=RepositoryIdentity(COMMIT, TREE, dirty=True),
        )
    with pytest.raises(ValueError, match="wrong evaluator identity"):
        execute_measured_b0(
            authorization=replace(auth, evaluator_behavior_identity="99" * 32),
            census=census,
            evaluator_cases=cases,
            manifest=manifest,
            adapter=adapter,
            config=config,
            repository=_clean_repo(),
        )
    with pytest.raises(ValueError, match="wrong corpus digest"):
        execute_measured_b0(
            authorization=replace(auth, corpus_manifest_digest="aa" * 32),
            census=census,
            evaluator_cases=cases,
            manifest=manifest,
            adapter=adapter,
            config=config,
            repository=_clean_repo(),
        )
    with pytest.raises(ValueError, match="wrong commit"):
        execute_measured_b0(
            authorization=replace(auth, repository_commit="ee" * 20),
            census=census,
            evaluator_cases=cases,
            manifest=manifest,
            adapter=adapter,
            config=config,
            repository=_clean_repo(),
        )


def test_aggregate_three_compatible_records_and_refusals() -> None:
    cases, manifest, census, config = _build_fixture()
    documents = {
        case.case_id: _document(case, prompt=config.prompt_config_identity) for case in cases
    }
    records, _state = execute_measured_b0(
        authorization=_fixture_auth(census, manifest, config),
        census=census,
        evaluator_cases=cases,
        manifest=manifest,
        adapter=RecordingFakeAdapter(documents),
        config=config,
        repository=_clean_repo(),
        measured_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    summary = aggregate_b0_measurements(records)
    assert summary.repetition_count == 3
    assert summary.mean_gsqs == pytest.approx(sum(summary.gsqs_values) / 3)
    assert summary.median_gsqs == sorted(summary.gsqs_values)[1]
    assert summary.range_gsqs == summary.max_gsqs - summary.min_gsqs
    assert summary.stdev_gsqs == pytest.approx(0.0)
    assert summary.measured_b0 == MEASURED_B0_NOT_YET_ESTABLISHED
    assert summary.self_improvement == SELF_IMPROVEMENT_NOT_YET_ACTIVATED
    assert summary.automatic_promotion == AUTOMATIC_PROMOTION_DISABLED
    dumped = json.dumps(asdict(summary), default=str).lower()
    assert "promote" not in dumped
    assert "production ready" not in dumped
    with pytest.raises(ValueError, match="fewer than minimum repetitions"):
        aggregate_b0_measurements(records[:2])
    mixed = replace(records[2], candidate_config_digest="ff" * 32)
    with pytest.raises(ValueError, match="mixed candidate_config_digest"):
        aggregate_b0_measurements((*records[:2], mixed))
    invalid = replace(records[1], measurement_valid=False, invalid_reason="synthetic")
    with pytest.raises(ValueError, match="invalid measurement rejected"):
        aggregate_b0_measurements((*records[:1], invalid, records[2]))
    assert GATE_B_STATE["MEASURED_B0"] == MEASURED_B0_NOT_YET_ESTABLISHED


def test_unbound_adapter_and_cli_make_zero_external_calls(tmp_path: Path) -> None:
    cases, manifest, census, config = _build_fixture()
    with pytest.raises(ValueError, match="incumbent transport is not bound"):
        execute_measured_b0(
            authorization=_fixture_auth(census, manifest, config),
            census=census,
            evaluator_cases=cases,
            manifest=manifest,
            adapter=UnboundIncumbentAdapter(),
            config=config,
            repository=_clean_repo(),
        )
    import apps.cli.gsqs_b0 as cli

    assert "httpx" not in inspect.getsource(cli)
    assert "openai" not in inspect.getsource(cli)
    report = preflight(catalog=_catalog(), repository=_clean_repo())
    written = write_public_evidence(tmp_path, report=report)
    assert "RUN_CONTROL.json" in written
    control = json.loads((tmp_path / "RUN_CONTROL.json").read_text())
    assert control["MEASURED_B0"] == MEASURED_B0_NOT_YET_ESTABLISHED
    assert control["disclosure_would_occur"] is False


def test_census_rejects_wrong_b_count() -> None:
    catalog = copy.deepcopy(_catalog())
    for case in catalog["cases"]:  # type: ignore[union-attr]
        if case["partition"] == "B" and not case["excluded"] and case["review_state"] == "APPROVED":
            case["excluded"] = True
            break
    with pytest.raises(ValueError, match="not 73"):
        partition_b_census(catalog)
