"""GSQS B0 RouteLLM-over-MCP evaluation bindings, capture admit-and-score, no HTTP."""

from __future__ import annotations

import inspect
import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs import (
    MEASURED_B0_NOT_YET_ESTABLISHED,
    evaluator_code_identity,
)
from my_pa.application.goodnotes_gsqs_b0_mcp import (
    CAPTURE_SCHEMA_VERSION,
    LIVE_REMOTE_MCP_ORIGIN,
    MCP_BINDING_ISOLATED_IN_PROCESS,
    MCP_EVALUATION_SURFACE_STDIO,
    CapturedAnalyzerAdapter,
    evaluation_handle,
    load_captured_repetitions,
    load_evaluation_png,
    pin_evaluation_raster,
    validate_mcp_evaluation_bindings,
)
from my_pa.application.goodnotes_gsqs_corpus import CorpusCase, CorpusManifest
from my_pa.application.goodnotes_gsqs_live_b0 import (
    B0Census,
    B0CensusMember,
    ExecutionAuthorization,
    FrozenAnalyzerConfig,
    aggregate_b0_measurements,
    execute_measured_b0,
    write_evaluation_handles,
)
from my_pa.infrastructure.gsqs_b0_evaluation import (
    GsqsB0EvaluationError,
    GsqsB0EvaluationUnitOfWork,
)
from tests.conftest import _staged_gray_png
from tests.unit.test_goodnotes_gsqs_live_b0 import (
    MODEL,
    _auth,
    _build_fixture,
    _clean_repo,
    _document,
    _DurableFake,
    _fixture_auth,
)


def _mcp_auth(
    census: B0Census, manifest: CorpusManifest, config: FrozenAnalyzerConfig
) -> ExecutionAuthorization:
    return replace(
        _fixture_auth(census, manifest, config),
        mcp_evaluation_surface=MCP_EVALUATION_SURFACE_STDIO,
        mcp_evaluation_binding_mode=MCP_BINDING_ISOLATED_IN_PROCESS,
        mcp_evaluation_evidence_id="synthetic-mcp-eval",
    )


def _write_captures(
    directory: Path, cases: Sequence[CorpusCase], config: FrozenAnalyzerConfig
) -> None:
    documents = [_document(case, prompt=config.prompt_config_identity) for case in cases]
    payload = {"documents": documents, "schema_version": CAPTURE_SCHEMA_VERSION}
    for index in range(1, 4):
        (directory / f"repetition-{index:03d}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )


def test_live_remote_mcp_origin_is_not_an_evaluation_surface() -> None:
    with pytest.raises(ValueError, match="live remote MCP"):
        validate_mcp_evaluation_bindings(
            _auth(
                mcp_evaluation_surface=LIVE_REMOTE_MCP_ORIGIN,
                mcp_evaluation_binding_mode=MCP_BINDING_ISOLATED_IN_PROCESS,
                mcp_evaluation_evidence_id="x",
            )
        )


def test_mcp_bindings_require_stdio_isolated_surface() -> None:
    with pytest.raises(ValueError, match="mcp_evaluation_surface"):
        validate_mcp_evaluation_bindings(
            _auth(
                mcp_evaluation_binding_mode=MCP_BINDING_ISOLATED_IN_PROCESS,
                mcp_evaluation_evidence_id="x",
            )
        )
    validate_mcp_evaluation_bindings(
        _auth(
            mcp_evaluation_surface=MCP_EVALUATION_SURFACE_STDIO,
            mcp_evaluation_binding_mode=MCP_BINDING_ISOLATED_IN_PROCESS,
            mcp_evaluation_evidence_id="eval-1",
        )
    )


def test_raster_digest_mismatch_is_refused(tmp_path: Path) -> None:
    png = _staged_gray_png()
    digest = sha256(png).hexdigest()
    member = B0CensusMember(
        case_id="case-a",
        raster_sha256=digest,
        case_digest="aa" * 32,
        file_sha256=digest,
    )
    (tmp_path / "case-a.png").write_bytes(png)
    work = evaluation_handle(member, principal_id="prn_" + "a" * 32)
    pin_evaluation_raster(work, png, created_at=datetime(2026, 8, 22, tzinfo=UTC))
    with pytest.raises(ValueError, match="raster digest mismatch"):
        pin_evaluation_raster(work, png + b"x", created_at=datetime(2026, 8, 22, tzinfo=UTC))
    assert load_evaluation_png(tmp_path, "case-a") == png


def test_evaluation_unit_of_work_refuses_propose() -> None:
    png = _staged_gray_png()
    digest = sha256(png).hexdigest()
    member = B0CensusMember(
        case_id="case-a",
        raster_sha256=digest,
        case_digest="aa" * 32,
        file_sha256=digest,
    )
    work = evaluation_handle(member, principal_id="prn_" + "a" * 32)
    raster = pin_evaluation_raster(work, png, created_at=datetime(2026, 8, 22, tzinfo=UTC))
    with GsqsB0EvaluationUnitOfWork(((work, raster),)) as unit:
        found = unit.goodnotes_semantics.page_work(
            work.principal_id, work.run_id, work.page_version_id
        )
        assert found is not None
        with pytest.raises(GsqsB0EvaluationError):
            unit.goodnotes_semantics.submit_proposal(
                principal_id=work.principal_id,
                run_id=work.run_id,
                page_version_id=work.page_version_id,
                content_sha256=digest,
                schema_version="note-unit.v2",
                analyzer_name="x",
                analyzer_version="1",
                idempotency_key="k",
                request_fingerprint="f",
                payload_sha256="bb" * 32,
                payload={},
                correlation_id="cor_" + "a" * 24,
                request_id="req_" + "a" * 24,
                audit_id=None,
                created_at=datetime(2026, 8, 22, tzinfo=UTC),
            )


def test_captured_output_admits_and_scores_without_routellm_http(tmp_path: Path) -> None:
    cases, manifest, census, config = _build_fixture()
    _write_captures(tmp_path, cases, config)
    repetitions = load_captured_repetitions(tmp_path, census)
    records, state = execute_measured_b0(
        authorization=_mcp_auth(census, manifest, config),
        census=census,
        evaluator_cases=cases,
        manifest=manifest,
        adapter=CapturedAnalyzerAdapter(repetitions),
        config=config,
        repository=_clean_repo(),
        image_loader=None,
        measured_at=datetime(2026, 8, 22, tzinfo=UTC),
    )
    summary = aggregate_b0_measurements(records)
    assert state.value == "COMPLETE"
    assert len(records) == 3
    assert summary.measured_b0 == MEASURED_B0_NOT_YET_ESTABLISHED
    assert summary.evaluator_code_identity == evaluator_code_identity()


def test_durable_mcp_bindings_do_not_require_http_origin(tmp_path: Path) -> None:
    from my_pa.application.goodnotes_gsqs_b0_disclosure_journal import DisclosureJournal

    cases, manifest, census, config = _build_fixture()
    documents = {
        case.case_id: _document(case, prompt=config.prompt_config_identity) for case in cases
    }
    journal = DisclosureJournal(tmp_path, run_id="synthetic-mcp")
    records, _state = execute_measured_b0(
        authorization=_mcp_auth(census, manifest, config),
        census=census,
        evaluator_cases=cases,
        manifest=manifest,
        adapter=_DurableFake(documents),
        config=config,
        repository=_clean_repo(),
        disclosure_journal=journal,
        measured_at=datetime(2026, 8, 22, tzinfo=UTC),
    )
    assert len(records) == 3


def test_captured_census_mismatch_is_rejected(tmp_path: Path) -> None:
    cases, _manifest, census, config = _build_fixture()
    documents = [_document(case, prompt=config.prompt_config_identity) for case in cases]
    documents.append(dict(documents[0]))
    payload = {"documents": documents, "schema_version": CAPTURE_SCHEMA_VERSION}
    for index in range(1, 4):
        (tmp_path / f"repetition-{index:03d}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    with pytest.raises(ValueError, match="Partition B census"):
        load_captured_repetitions(tmp_path, census)


def test_score_cli_requires_authorization_and_does_not_use_http(tmp_path: Path) -> None:
    import apps.cli.gsqs_b0 as cli

    assert (
        cli.main(
            [
                "score",
                "--model-identity",
                MODEL,
                "--prompt-config",
                "x",
                "--repetitions",
                "3",
                "--evaluator-corpus",
                "synthetic-evaluator.json",
                "--analyzer-output-dir",
                str(tmp_path),
                "--evidence-dir",
                str(tmp_path / "evidence"),
            ]
        )
        == 1
    )
    source = inspect.getsource(cli._score)
    assert "API_KEY_ENV" not in source
    assert "get_models" not in source
    assert "httpx" not in inspect.getsource(cli)
    parsed = cli.build_parser().parse_args(
        [
            "score",
            "--authorization",
            "auth.json",
            "--model-identity",
            MODEL,
            "--prompt-config",
            "x",
            "--repetitions",
            "3",
            "--evaluator-corpus",
            "synthetic-evaluator.json",
            "--analyzer-output-dir",
            str(tmp_path),
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ]
    )
    assert parsed.command == "score"
    parsed_eval = cli.build_parser().parse_args(["serve-eval-mcp", "--authorization", "auth.json"])
    assert parsed_eval.command == "serve-eval-mcp"


def test_evaluation_handles_are_public_identities_only(tmp_path: Path) -> None:
    written = write_evaluation_handles(
        tmp_path,
        (
            {
                "case_id": "case-a",
                "run_id": "gnrun_" + "a" * 24,
                "page_version_id": "gnver_" + "b" * 24,
                "content_sha256": "aa" * 32,
                "raster_sha256": "aa" * 32,
            },
        ),
    )
    payload = json.loads((tmp_path / "EVALUATION_HANDLES.json").read_text(encoding="utf-8"))
    dumped = json.dumps(payload).lower()
    assert "EVALUATION_HANDLES.json" in written
    assert "gold" not in dumped
    assert "transcription" not in dumped
    assert "content_base64" not in dumped
