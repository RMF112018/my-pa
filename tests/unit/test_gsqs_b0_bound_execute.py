"""Bound CLI execute: evaluator plane before probe, evidence refresh on failure."""

from __future__ import annotations

import json
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

import pytest
from apps.cli.gsqs_b0 import EXIT_OK, RouteLLMIncumbentAdapter, run_bound_execute

from my_pa.application.goodnotes_gsqs import evaluator_code_identity
from my_pa.application.goodnotes_gsqs_b0_disclosure_journal import (
    EVENT_STARTED,
    DisclosureJournal,
)
from my_pa.application.goodnotes_gsqs_corpus import CorpusCase, dump_evaluator_plane_cases
from my_pa.application.goodnotes_gsqs_harness import INTERCHANGE_SCHEMA_VERSION
from my_pa.application.goodnotes_gsqs_live_b0 import (
    AnalyzerCaseInput,
    B0Census,
    B0RunState,
    FrozenAnalyzerConfig,
    PreflightReport,
    RecordingFakeAdapter,
)
from my_pa.infrastructure.gsqs_routellm_transport import (
    RouteLLMHttpResult,
    RouteLLMPostResponseError,
    RouteLLMTransportError,
)
from tests.unit.test_goodnotes_gsqs_live_b0 import (
    COMMIT,
    MODEL,
    TREE,
    _build_fixture,
    _clean_repo,
    _document,
    _DurableFake,
    _route_auth,
)


def _pages(cases: tuple[CorpusCase, ...]) -> Callable[[str], bytes]:
    rasters = {item.case_id: item.page_bytes for item in cases}

    def load(case_id: str) -> bytes:
        return rasters[case_id]

    return load


def _report(census: B0Census, config: FrozenAnalyzerConfig) -> PreflightReport:
    return PreflightReport(
        go=True,
        state=B0RunState.PREPARED,
        reasons=(),
        corpus_version=census.corpus_version,
        manifest_digest=census.manifest_digest,
        combined_identity=census.combined_identity,
        scoreable_b=len(census.members),
        census_digest=census.census_digest,
        analyzer_name=config.analyzer_name,
        analyzer_version=config.analyzer_version,
        prompt_config_identity=config.prompt_config_identity,
        evaluator_behavior_identity=evaluator_code_identity(),
        repository_commit=COMMIT,
        repository_tree=TREE,
        disclosure_would_occur=False,
    )


class _RaisingAdapter:
    requires_durable_disclosure_journal = True

    def __init__(self, error: Exception) -> None:
        self._error = error

    def analyze(self, case: AnalyzerCaseInput, config: FrozenAnalyzerConfig) -> dict[str, object]:
        del case, config
        raise self._error


class _CountingAdapter(RecordingFakeAdapter):
    requires_durable_disclosure_journal = True

    def __init__(self, documents: dict[str, dict[str, object]], posts: list[int]) -> None:
        super().__init__(documents)
        self._posts = posts

    def analyze(self, case: AnalyzerCaseInput, config: FrozenAnalyzerConfig) -> dict[str, object]:
        self._posts.append(1)
        return super().analyze(case, config)


def test_wrong_evaluator_cases_do_not_probe(tmp_path: Path) -> None:
    _cases, manifest, census, config = _build_fixture()
    probes: list[int] = []

    def probe(**_kwargs: object) -> RouteLLMHttpResult:
        probes.append(1)
        return RouteLLMHttpResult(status=200, payload={"data": []})

    with pytest.raises(ValueError, match="evaluator cases do not match"):
        run_bound_execute(
            authorization=_route_auth(census, manifest, config),
            report=_report(census, config),
            census=census,
            evaluator_cases=(),
            manifest=manifest,
            config=config,
            repository=_clean_repo(),
            adapter=_DurableFake({}),
            evidence_dir=tmp_path,
            identity=MODEL,
            origin="https://route.example",
            api_key="k",
            image_loader=_pages(_cases),
            probe=probe,
        )
    assert probes == []
    journal = tmp_path / "disclosure_journal.jsonl"
    assert not journal.exists() or EVENT_STARTED not in journal.read_text()


def test_probe_failure_does_not_post_and_writes_none(tmp_path: Path) -> None:
    cases, manifest, census, config = _build_fixture()
    posts: list[int] = []
    documents = {
        case.case_id: _document(case, prompt=config.prompt_config_identity) for case in cases
    }

    def probe(**_kwargs: object) -> RouteLLMHttpResult:
        raise RouteLLMTransportError("dns", error_class="URL_ERROR", disclosed=False)

    with pytest.raises(RouteLLMTransportError, match="dns"):
        run_bound_execute(
            authorization=_route_auth(census, manifest, config),
            report=_report(census, config),
            census=census,
            evaluator_cases=cases,
            manifest=manifest,
            config=config,
            repository=_clean_repo(),
            adapter=_CountingAdapter(documents, posts),
            evidence_dir=tmp_path,
            identity=MODEL,
            origin="https://route.example",
            api_key="k",
            image_loader=_pages(cases),
            probe=probe,
        )
    assert posts == []
    control = json.loads((tmp_path / "RUN_CONTROL.json").read_text())
    assert control["EXTERNAL_MODEL_DISCLOSURE"] == "NONE"
    assert control["started_request_count"] == 0
    gold = cases[0].regions[0].transcription
    packed = (tmp_path / "RUN_CONTROL.json").read_text() + (
        tmp_path / "ANALYZER_CONFIG.json"
    ).read_text()
    if (tmp_path / "disclosure_journal.jsonl").exists():
        packed += (tmp_path / "disclosure_journal.jsonl").read_text()
    assert gold not in packed


def test_successful_probe_permits_fake_post(tmp_path: Path) -> None:
    cases, manifest, census, config = _build_fixture()
    probes: list[int] = []
    documents = {
        case.case_id: _document(case, prompt=config.prompt_config_identity) for case in cases
    }

    def probe(**_kwargs: object) -> RouteLLMHttpResult:
        probes.append(1)
        return RouteLLMHttpResult(status=200, payload={"data": []})

    result = run_bound_execute(
        authorization=_route_auth(census, manifest, config),
        report=_report(census, config),
        census=census,
        evaluator_cases=cases,
        manifest=manifest,
        config=config,
        repository=_clean_repo(),
        adapter=_DurableFake(documents),
        evidence_dir=tmp_path,
        identity=MODEL,
        origin="https://route.example",
        api_key="k",
        image_loader=_pages(cases),
        probe=probe,
    )
    assert result == EXIT_OK
    assert probes == [1]
    control = json.loads((tmp_path / "RUN_CONTROL.json").read_text())
    assert control["EXTERNAL_MODEL_DISCLOSURE"] == "COMPLETE"
    assert control["MEASURED_B0"] == "NOT_YET_ESTABLISHED"
    index = json.loads((tmp_path / "EVIDENCE_INDEX.json").read_text())
    journal_digest = index["digests"]["disclosure_journal.jsonl"]
    assert (
        journal_digest == sha256((tmp_path / "disclosure_journal.jsonl").read_bytes()).hexdigest()
    )
    gold = cases[0].regions[0].transcription
    public = "".join(path.read_text() for path in tmp_path.iterdir() if path.is_file())
    assert gold not in public
    dumped = json.dumps(dump_evaluator_plane_cases(cases))
    assert gold in dumped


def test_transport_error_refreshes_public_may_have_occurred(tmp_path: Path) -> None:
    cases, manifest, census, config = _build_fixture()

    def probe(**_kwargs: object) -> RouteLLMHttpResult:
        return RouteLLMHttpResult(status=200, payload={"data": []})

    with pytest.raises(RouteLLMTransportError, match="timeout"):
        run_bound_execute(
            authorization=_route_auth(census, manifest, config),
            report=_report(census, config),
            census=census,
            evaluator_cases=cases,
            manifest=manifest,
            config=config,
            repository=_clean_repo(),
            adapter=_RaisingAdapter(
                RouteLLMTransportError("timeout", error_class="TIMEOUT", disclosed=None)
            ),
            evidence_dir=tmp_path,
            identity=MODEL,
            origin="https://route.example",
            api_key="k",
            image_loader=_pages(cases),
            probe=probe,
        )
    control = json.loads((tmp_path / "RUN_CONTROL.json").read_text())
    assert control["EXTERNAL_MODEL_DISCLOSURE"] == "MAY_HAVE_OCCURRED"
    assert control["started_request_count"] >= 1


def test_http_error_refreshes_confirmed_disclosed(tmp_path: Path) -> None:
    cases, manifest, census, config = _build_fixture()

    def probe(**_kwargs: object) -> RouteLLMHttpResult:
        return RouteLLMHttpResult(status=200, payload={"data": []})

    with pytest.raises(RouteLLMTransportError):
        run_bound_execute(
            authorization=_route_auth(census, manifest, config),
            report=_report(census, config),
            census=census,
            evaluator_cases=cases,
            manifest=manifest,
            config=config,
            repository=_clean_repo(),
            adapter=_RaisingAdapter(
                RouteLLMTransportError(
                    "429", http_status=429, error_class="HTTP_429", disclosed=True
                )
            ),
            evidence_dir=tmp_path,
            identity=MODEL,
            origin="https://route.example",
            api_key="k",
            image_loader=_pages(cases),
            probe=probe,
        )
    control = json.loads((tmp_path / "RUN_CONTROL.json").read_text())
    assert control["EXTERNAL_MODEL_DISCLOSURE"] == "CONFIRMED_DISCLOSED"


def test_malformed_semantic_refreshes_confirmed(tmp_path: Path) -> None:
    cases, manifest, census, config = _build_fixture()

    def probe(**_kwargs: object) -> RouteLLMHttpResult:
        return RouteLLMHttpResult(status=200, payload={"data": []})

    with pytest.raises(RouteLLMPostResponseError):
        run_bound_execute(
            authorization=_route_auth(census, manifest, config),
            report=_report(census, config),
            census=census,
            evaluator_cases=cases,
            manifest=manifest,
            config=config,
            repository=_clean_repo(),
            adapter=_RaisingAdapter(
                RouteLLMPostResponseError(
                    "malformed semantic payload",
                    http_status=200,
                    error_class="MALFORMED_SEMANTIC",
                )
            ),
            evidence_dir=tmp_path,
            identity=MODEL,
            origin="https://route.example",
            api_key="k",
            image_loader=_pages(cases),
            probe=probe,
        )
    control = json.loads((tmp_path / "RUN_CONTROL.json").read_text())
    assert control["EXTERNAL_MODEL_DISCLOSURE"] == "CONFIRMED_DISCLOSED"


def test_restart_rebuilds_may_have_occurred_before_refuse(tmp_path: Path) -> None:
    cases, manifest, census, config = _build_fixture()
    prior = DisclosureJournal(tmp_path, run_id="synthetic-auth")
    prior.record_started(
        repetition=1, case_id=cases[0].case_id, raster_sha256=cases[0].content_sha256
    )
    (tmp_path / "RUN_CONTROL.json").write_text(
        json.dumps({"EXTERNAL_MODEL_DISCLOSURE": "NONE"}, indent=2) + "\n"
    )
    probes: list[int] = []

    def probe(**_kwargs: object) -> RouteLLMHttpResult:
        probes.append(1)
        return RouteLLMHttpResult(status=200, payload={"data": []})

    with pytest.raises(ValueError, match="unresolved disclosure attempt"):
        run_bound_execute(
            authorization=_route_auth(census, manifest, config),
            report=_report(census, config),
            census=census,
            evaluator_cases=cases,
            manifest=manifest,
            config=config,
            repository=_clean_repo(),
            adapter=_DurableFake({}),
            evidence_dir=tmp_path,
            identity=MODEL,
            origin="https://route.example",
            api_key="k",
            image_loader=_pages(cases),
            probe=probe,
        )
    assert probes == []
    control = json.loads((tmp_path / "RUN_CONTROL.json").read_text())
    assert control["EXTERNAL_MODEL_DISCLOSURE"] == "MAY_HAVE_OCCURRED"


def test_mapped_out_of_pool_refreshes_invalid_public(tmp_path: Path) -> None:
    from my_pa.application.goodnotes_gsqs_provider_model_mapping import mapping_from_payload

    cases, manifest, census, config = _build_fixture()
    documents = {
        case.case_id: _document(case, prompt=config.prompt_config_identity) for case in cases
    }
    first_id = census.members[0].case_id
    documents[first_id]["selected_model"] = "mystery-out"
    mapping = mapping_from_payload(
        {
            "evidence_id": "map-1",
            "mapping_schema_version": "gsqs-b0-provider-model-mapping-v1",
            "entries": [
                {
                    "display_name": "mystery-out",
                    "pool_membership": "OUT_OF_POOL",
                    "provider_model_id": "mystery-out",
                }
            ],
        },
        expected_evidence_id="map-1",
    )

    def probe(**_kwargs: object) -> RouteLLMHttpResult:
        return RouteLLMHttpResult(status=200, payload={"data": []})

    with pytest.raises(ValueError, match="mapped out of pool"):
        run_bound_execute(
            authorization=_route_auth(census, manifest, config),
            report=_report(census, config),
            census=census,
            evaluator_cases=cases,
            manifest=manifest,
            config=config,
            repository=_clean_repo(),
            adapter=_DurableFake(documents),
            evidence_dir=tmp_path,
            identity=MODEL,
            origin="https://route.example",
            api_key="k",
            image_loader=_pages(cases),
            mapping=mapping,
            probe=probe,
        )
    control = json.loads((tmp_path / "RUN_CONTROL.json").read_text())
    assert control["EXTERNAL_MODEL_DISCLOSURE"] == "INVALID"
    gold = cases[0].regions[0].transcription
    packed = "".join(path.read_text() for path in tmp_path.iterdir() if path.is_file())
    assert gold not in packed


def test_http_body_and_prompt_exclude_evaluator_gold() -> None:
    from my_pa.application.goodnotes_gsqs_routellm_envelope import build_chat_completions_body

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    cases, _manifest, _census, config = _build_fixture()
    gold = cases[0].regions[0].transcription
    captured: dict[str, object] = {}

    def poster(*, origin: str, api_key: str, body: object) -> RouteLLMHttpResult:
        del origin, api_key
        captured["body"] = body
        return RouteLLMHttpResult(
            status=200,
            payload={"choices": [{"message": {"content": "not-json"}}], "model": "route-llm"},
        )

    case = AnalyzerCaseInput(
        case_id=cases[0].case_id,
        corpus_version=cases[0].corpus_version,
        raster_sha256=cases[0].content_sha256,
        interchange_schema_version=INTERCHANGE_SCHEMA_VERSION,
        image_bytes=png,
    )
    adapter = RouteLLMIncumbentAdapter(origin="https://route.example", api_key="k", poster=poster)
    with pytest.raises(RouteLLMPostResponseError):
        adapter.analyze(case, config)
    encoded = json.dumps(captured["body"])
    assert gold not in encoded
    assert gold not in str(config.prompt_text)
    body = build_chat_completions_body(case, config, image_bytes=png, mime="image/png")
    assert gold not in json.dumps(body)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    cases, _manifest, _census, config = _build_fixture()
    case = AnalyzerCaseInput(
        case_id=cases[0].case_id,
        corpus_version=cases[0].corpus_version,
        raster_sha256=cases[0].content_sha256,
        interchange_schema_version=INTERCHANGE_SCHEMA_VERSION,
        image_bytes=png,
    )

    def poster(**_kwargs: object) -> RouteLLMHttpResult:
        return RouteLLMHttpResult(
            status=200,
            payload={"choices": [{"message": {"content": "not-json"}}]},
        )

    adapter = RouteLLMIncumbentAdapter(origin="https://route.example", api_key="k", poster=poster)
    with pytest.raises(RouteLLMPostResponseError) as raised:
        adapter.analyze(case, config)
    assert raised.value.http_status == 200
    assert raised.value.disclosed is True
    assert "gold" not in json.dumps(poster().payload)
