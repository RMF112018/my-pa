"""B0-EXEC-001/002/003 local execution infrastructure. Synthetic rasters only."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import apps.cli.gsqs_b0 as cli
import pytest

from my_pa.application.goodnotes_gsqs import (
    evaluator_code_identity,
    evaluator_implementation_digest,
)
from my_pa.application.goodnotes_gsqs_b0_acquisition import (
    ACQUISITION_AUTH_SCHEMA,
    CAMPAIGN_CLASS_REAL,
    CAMPAIGN_CLASS_SYNTHETIC,
    MODEL_CLIENT_ROUTELLM_HTTP,
    MODEL_CLIENT_SYNTHETIC,
    OPERATION_REAL,
    OPERATION_SYNTHETIC,
    AcquisitionError,
    assert_acquisition_permitted,
    is_real_handwriting_campaign,
    load_acquisition_authorization,
)
from my_pa.application.goodnotes_gsqs_b0_capture import (
    CaptureBinding,
    CaptureWriterError,
    capture_payload,
    write_repetition_capture,
)
from my_pa.application.goodnotes_gsqs_b0_mcp import (
    CAPTURE_SCHEMA_VERSION,
    MCP_BINDING_OPERATOR_LOCAL_STDIO,
    MCP_EVALUATION_SURFACE_STDIO,
    load_captured_repetitions,
)
from my_pa.application.goodnotes_gsqs_b0_model_client import (
    ROUTELLM_ACTIVATION_BLOCKER,
    B0ModelClientError,
    RouteLLMClientActivationError,
    SyntheticB0ModelClient,
    TimeoutB0ModelClient,
    bind_model_client,
)
from my_pa.application.goodnotes_gsqs_b0_orchestrator import (
    AcquisitionState,
    OrchestratorError,
    acquire_repetition,
)
from my_pa.application.goodnotes_gsqs_b0_stdio_session import StdioEvalSession, StdioHostError
from my_pa.application.goodnotes_gsqs_b0_synthetic_campaign import (
    SYNTHETIC_CASE_COUNT,
    SyntheticCampaign,
    build_synthetic_campaign,
)
from my_pa.application.goodnotes_gsqs_harness import (
    INCUMBENT_ANALYZER_NAME,
    INCUMBENT_ANALYZER_VERSION,
)
from my_pa.application.goodnotes_gsqs_hw_corpus import HANDWRITING_CORPUS_VERSION
from my_pa.application.goodnotes_gsqs_live_b0 import (
    APPROVED_COMBINED_IDENTITY,
    AnalyzerCaseInput,
    FrozenAnalyzerConfig,
    frozen_incumbent_config,
    prompt_config_identity,
    repo_root,
)
from my_pa.application.goodnotes_gsqs_routellm_candidate import (
    composite_model_identity,
    load_route_llm_candidate,
)

EVALUATOR_BEHAVIOR_SHA = "d2bd088a098f99d31637069fd339a67d665b80eb7aa97b403367cce1011a3fb7"
EVALUATOR_IMPLEMENTATION_SHA = "a8f26fb28e2bb4cce1a2a3e6745dd01a2bdf5e2deaff63d9d05977bbfc9815ba"
ROOT = repo_root()


class FakeContentSession:
    def __init__(
        self,
        rasters: dict[str, bytes],
        *,
        tools: tuple[str, ...] = ("goodnotes.content", "goodnotes.work"),
        fail_on: str | None = None,
        crash_between: str | None = None,
        missing: str | None = None,
        mismatch: str | None = None,
    ) -> None:
        self.rasters = rasters
        self.tools = tools
        self.fail_on = fail_on
        self.crash_between = crash_between
        self.missing = missing
        self.mismatch = mismatch
        self.closed = False
        self.fetched: list[str] = []

    def initialize_and_list_tools(self) -> tuple[str, ...]:
        return self.tools

    def fetch_png(self, *, case_id: str, expected_sha256: str) -> bytes:
        if self.crash_between is not None and self.fetched and case_id == self.crash_between:
            raise OrchestratorError("process crash")
        if case_id == self.fail_on:
            raise OrchestratorError("process crash")
        if case_id == self.missing:
            raise OrchestratorError("raster missing")
        png = self.rasters[case_id]
        if case_id == self.mismatch:
            png = png + b"x"
        self.fetched.append(case_id)
        del expected_sha256
        return png

    def close(self) -> None:
        self.closed = True


def _identities() -> tuple[str, str, FrozenAnalyzerConfig]:
    candidate_path = ROOT / "ops/goodnotes/gsqs/b0/routellm-goodnotes-b0-v1.json"
    candidate = load_route_llm_candidate(candidate_path)
    identity = composite_model_identity(candidate)
    config = frozen_incumbent_config(model_identity=identity, root=ROOT)
    return identity, prompt_config_identity(ROOT), config


def _auth_payload(
    campaign: SyntheticCampaign, *, repetition: int = 1, **overrides: object
) -> dict[str, object]:
    identity, prompt, _config = _identities()
    payload: dict[str, object] = {
        "analyzer_name": INCUMBENT_ANALYZER_NAME,
        "analyzer_version": INCUMBENT_ANALYZER_VERSION,
        "authorization_id": "synthetic-b0-exec-001",
        "campaign_class": CAMPAIGN_CLASS_SYNTHETIC,
        "campaign_id": campaign.campaign_id,
        "candidate_identity": identity,
        "combined_identity": campaign.combined_identity,
        "corpus_manifest_digest": campaign.manifest_digest,
        "corpus_version": campaign.corpus_version,
        "mcp_evaluation_binding_mode": MCP_BINDING_OPERATOR_LOCAL_STDIO,
        "mcp_evaluation_evidence_id": "synthetic-stdio-host",
        "mcp_evaluation_surface": MCP_EVALUATION_SURFACE_STDIO,
        "model_client": MODEL_CLIENT_SYNTHETIC,
        "model_identity": identity,
        "operation": OPERATION_SYNTHETIC,
        "prompt_config_identity": prompt,
        "repetition": repetition,
        "schema_version": ACQUISITION_AUTH_SCHEMA,
    }
    payload.update(overrides)
    return payload


def _write_auth(path: Path, campaign: SyntheticCampaign, **overrides: object) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    target = path / "authorization.json"
    target.write_text(json.dumps(_auth_payload(campaign, **overrides), indent=2), encoding="utf-8")
    return target


def _rasters(campaign: SyntheticCampaign) -> dict[str, bytes]:
    return {
        member.case_id: (campaign.raster_root / f"{member.case_id}.png").read_bytes()
        for member in campaign.census.members
    }


def _binding(campaign: SyntheticCampaign, *, repetition: int = 1) -> CaptureBinding:
    identity, prompt, config = _identities()
    return CaptureBinding(
        campaign_id=campaign.campaign_id,
        corpus_version=campaign.corpus_version,
        combined_identity=campaign.combined_identity,
        repetition=repetition,
        candidate_identity=identity,
        model_identity=config.model_identity,
        analyzer_name=config.analyzer_name,
        analyzer_version=config.analyzer_version,
        prompt_config_identity=prompt,
    )


def test_evaluator_identities_are_unchanged() -> None:
    assert evaluator_code_identity() == EVALUATOR_BEHAVIOR_SHA
    assert evaluator_implementation_digest() == EVALUATOR_IMPLEMENTATION_SHA


def test_real_handwriting_campaign_is_detected() -> None:
    assert is_real_handwriting_campaign(
        corpus_version=HANDWRITING_CORPUS_VERSION, combined_identity="00" * 32
    )
    assert is_real_handwriting_campaign(
        corpus_version="other", combined_identity=APPROVED_COMBINED_IDENTITY
    )


def test_synthetic_campaign_is_not_real_handwriting(tmp_path: Path) -> None:
    campaign = build_synthetic_campaign(tmp_path, case_count=73)
    assert len(campaign.census.members) == SYNTHETIC_CASE_COUNT
    assert campaign.census.members[0].case_id == "synth-b0-001"
    assert campaign.census.members[-1].case_id == "synth-b0-073"
    assert not is_real_handwriting_campaign(
        corpus_version=campaign.corpus_version, combined_identity=campaign.combined_identity
    )


def test_real_corpus_fails_closed_without_authorization_a(tmp_path: Path) -> None:
    campaign = build_synthetic_campaign(tmp_path, case_count=2)
    auth = load_acquisition_authorization(_write_auth(tmp_path, campaign))
    with pytest.raises(AcquisitionError, match="REAL_HANDWRITING_B0_EXECUTION"):
        assert_acquisition_permitted(
            auth,
            repetition=1,
            corpus_version=HANDWRITING_CORPUS_VERSION,
            combined_identity=APPROVED_COMBINED_IDENTITY,
            model_identity=auth.model_identity,
            prompt_config_identity=auth.prompt_config_identity,
            candidate_identity=auth.candidate_identity,
            model_client=MODEL_CLIENT_SYNTHETIC,
        )
    real = load_acquisition_authorization(
        _write_auth(
            tmp_path,
            campaign,
            operation=OPERATION_REAL,
            campaign_class=CAMPAIGN_CLASS_REAL,
            corpus_version=HANDWRITING_CORPUS_VERSION,
            combined_identity=APPROVED_COMBINED_IDENTITY,
        )
    )
    with pytest.raises(AcquisitionError, match="not admitted"):
        assert_acquisition_permitted(
            real,
            repetition=1,
            corpus_version=HANDWRITING_CORPUS_VERSION,
            combined_identity=APPROVED_COMBINED_IDENTITY,
            model_identity=real.model_identity,
            prompt_config_identity=real.prompt_config_identity,
            candidate_identity=real.candidate_identity,
            model_client=MODEL_CLIENT_SYNTHETIC,
        )


def test_routellm_http_client_is_not_activated() -> None:
    with pytest.raises(RouteLLMClientActivationError, match=ROUTELLM_ACTIVATION_BLOCKER):
        bind_model_client(MODEL_CLIENT_ROUTELLM_HTTP)


def test_capture_writer_contract(tmp_path: Path) -> None:
    campaign = build_synthetic_campaign(tmp_path / "campaign", case_count=2)
    identity, prompt, config = _identities()
    client = SyntheticB0ModelClient()
    documents = []
    for member in campaign.census.members:
        png = (campaign.raster_root / f"{member.case_id}.png").read_bytes()
        documents.append(
            client.analyze(
                AnalyzerCaseInput(
                    case_id=member.case_id,
                    corpus_version=campaign.corpus_version,
                    raster_sha256=member.raster_sha256,
                    interchange_schema_version="gsqs-analyzer-output-v1",
                    image_bytes=png,
                ),
                config,
            )
        )
    first = write_repetition_capture(
        tmp_path / "out",
        binding=_binding(campaign),
        census=campaign.census,
        documents=documents,
    )
    again = write_repetition_capture(
        tmp_path / "out",
        binding=_binding(campaign),
        census=campaign.census,
        documents=documents,
    )
    assert first == again
    dumped = first.read_text(encoding="utf-8").lower()
    assert "gold" not in dumped
    assert "controlled_handwriting" not in dumped
    hostile = [dict(documents[0], case_id="other"), documents[1]]
    with pytest.raises(CaptureWriterError, match="do not match census"):
        capture_payload(binding=_binding(campaign), census=campaign.census, documents=hostile)
    conflict = [dict(documents[0], selected_model="other"), documents[1]]
    with pytest.raises(CaptureWriterError, match="conflicting"):
        write_repetition_capture(
            tmp_path / "out",
            binding=_binding(campaign),
            census=campaign.census,
            documents=conflict,
        )
    golded = [dict(documents[0], gold="nope"), documents[1]]
    with pytest.raises(CaptureWriterError, match="gold"):
        capture_payload(binding=_binding(campaign), census=campaign.census, documents=golded)
    del identity, prompt


def test_orchestrator_is_census_order_and_not_model_enumerated(tmp_path: Path) -> None:
    campaign = build_synthetic_campaign(tmp_path / "campaign", case_count=4)
    auth = load_acquisition_authorization(_write_auth(tmp_path, campaign))
    identity, _prompt, config = _identities()
    session = FakeContentSession(_rasters(campaign))
    result = acquire_repetition(
        authorization=auth,
        census=campaign.census,
        campaign_id=campaign.campaign_id,
        repetition=1,
        output_dir=tmp_path / "rep1",
        config=config,
        candidate_identity=identity,
        model_client=SyntheticB0ModelClient(),
        session=session,
    )
    assert result.state is AcquisitionState.COMPLETE
    assert result.captured == 4
    assert session.fetched == [item.case_id for item in campaign.census.members]
    assert session.closed is True
    payload = json.loads((tmp_path / "rep1" / "repetition-001.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == CAPTURE_SCHEMA_VERSION
    assert [item["case_id"] for item in payload["documents"]] == session.fetched


def test_tools_list_mismatch_fails_closed(tmp_path: Path) -> None:
    campaign = build_synthetic_campaign(tmp_path / "campaign", case_count=2)
    auth = load_acquisition_authorization(_write_auth(tmp_path, campaign))
    identity, _prompt, config = _identities()
    session = FakeContentSession(_rasters(campaign), tools=("goodnotes.work", "goodnotes.propose"))
    with pytest.raises(OrchestratorError, match="tools/list mismatch"):
        acquire_repetition(
            authorization=auth,
            census=campaign.census,
            campaign_id=campaign.campaign_id,
            repetition=1,
            output_dir=tmp_path / "bad-tools",
            config=config,
            candidate_identity=identity,
            model_client=SyntheticB0ModelClient(),
            session=session,
        )
    assert session.closed is True
    state = json.loads((tmp_path / "bad-tools" / "ACQUISITION_STATE.json").read_text())
    assert state["state"] == "INVALID"
    assert state["resumable"] is False


def test_failure_injection(tmp_path: Path) -> None:
    campaign = build_synthetic_campaign(tmp_path / "campaign", case_count=3)
    identity, prompt, config = _identities()
    cases = [
        ("raster missing", FakeContentSession(_rasters(campaign), missing="synth-b0-002")),
        ("raster hash mismatch", FakeContentSession(_rasters(campaign), mismatch="synth-b0-002")),
        ("process crash", FakeContentSession(_rasters(campaign), fail_on="synth-b0-002")),
        (
            "process crash between",
            FakeContentSession(_rasters(campaign), crash_between="synth-b0-003"),
        ),
    ]
    for label, session in cases:
        auth = load_acquisition_authorization(_write_auth(tmp_path / label, campaign))
        with pytest.raises((OrchestratorError, AcquisitionError)):
            acquire_repetition(
                authorization=auth,
                census=campaign.census,
                campaign_id=campaign.campaign_id,
                repetition=1,
                output_dir=tmp_path / label / "out",
                config=config,
                candidate_identity=identity,
                model_client=SyntheticB0ModelClient(),
                session=session,
            )
        assert session.closed is True
        state = json.loads((tmp_path / label / "out" / "ACQUISITION_STATE.json").read_text())
        assert state["resumable"] is False
        assert state["state"] in {"INVALID", "INTERRUPTED"}
    timeout_auth = load_acquisition_authorization(_write_auth(tmp_path / "timeout", campaign))
    with pytest.raises(B0ModelClientError, match="timeout"):
        acquire_repetition(
            authorization=timeout_auth,
            census=campaign.census,
            campaign_id=campaign.campaign_id,
            repetition=1,
            output_dir=tmp_path / "timeout" / "out",
            config=config,
            candidate_identity=identity,
            model_client=TimeoutB0ModelClient(),
            session=FakeContentSession(_rasters(campaign)),
        )
    drifted = FrozenAnalyzerConfig(
        analyzer_name=config.analyzer_name,
        analyzer_version=config.analyzer_version,
        model_identity="other-model",
        prompt_config_identity=prompt,
        prompt_text=config.prompt_text,
    )
    with pytest.raises(AcquisitionError, match="model identity drift"):
        acquire_repetition(
            authorization=load_acquisition_authorization(_write_auth(tmp_path / "drift", campaign)),
            census=campaign.census,
            campaign_id=campaign.campaign_id,
            repetition=1,
            output_dir=tmp_path / "drift" / "out",
            config=drifted,
            candidate_identity=identity,
            model_client=SyntheticB0ModelClient(),
            session=FakeContentSession(_rasters(campaign)),
        )
    with pytest.raises(AcquisitionError, match="authorization repetition mismatch"):
        acquire_repetition(
            authorization=load_acquisition_authorization(_write_auth(tmp_path / "rep2", campaign)),
            census=campaign.census,
            campaign_id=campaign.campaign_id,
            repetition=2,
            output_dir=tmp_path / "rep2" / "out",
            config=config,
            candidate_identity=identity,
            model_client=SyntheticB0ModelClient(),
            session=FakeContentSession(_rasters(campaign)),
        )
    first = tmp_path / "resume"
    acquire_repetition(
        authorization=load_acquisition_authorization(_write_auth(first, campaign)),
        census=campaign.census,
        campaign_id=campaign.campaign_id,
        repetition=1,
        output_dir=first / "out",
        config=config,
        candidate_identity=identity,
        model_client=SyntheticB0ModelClient(),
        session=FakeContentSession(_rasters(campaign)),
    )
    with pytest.raises(OrchestratorError, match="fresh repetition required"):
        acquire_repetition(
            authorization=load_acquisition_authorization(
                _write_auth(tmp_path / "resume2", campaign)
            ),
            census=campaign.census,
            campaign_id=campaign.campaign_id,
            repetition=1,
            output_dir=first / "out",
            config=config,
            candidate_identity=identity,
            model_client=SyntheticB0ModelClient(),
            session=FakeContentSession(_rasters(campaign)),
        )


def test_three_synthetic_repetitions_are_independent(tmp_path: Path) -> None:
    campaign = build_synthetic_campaign(tmp_path / "campaign", case_count=73)
    identity, _prompt, config = _identities()
    sessions: list[FakeContentSession] = []
    rows = []
    for repetition in (1, 2, 3):
        session = FakeContentSession(_rasters(campaign))
        sessions.append(session)
        result = acquire_repetition(
            authorization=load_acquisition_authorization(
                _write_auth(tmp_path / f"auth-{repetition}", campaign, repetition=repetition)
            ),
            census=campaign.census,
            campaign_id=campaign.campaign_id,
            repetition=repetition,
            output_dir=tmp_path / f"rep-{repetition:03d}",
            config=config,
            candidate_identity=identity,
            model_client=SyntheticB0ModelClient(),
            session=session,
        )
        payload = json.loads(
            (tmp_path / f"rep-{repetition:03d}" / f"repetition-{repetition:03d}.json").read_text()
        )
        case_ids = [item["case_id"] for item in payload["documents"]]
        assert case_ids == [item.case_id for item in campaign.census.members]
        assert len(case_ids) == 73
        assert len(set(case_ids)) == 73
        assert result.missing == 0
        assert result.duplicates == 0
        rows.append(result.captured)
        assert session.closed is True
    assert rows == [73, 73, 73]
    assert sessions[0] is not sessions[1]
    loader = tmp_path / "loader"
    loader.mkdir()
    for repetition in (1, 2, 3):
        src = tmp_path / f"rep-{repetition:03d}" / f"repetition-{repetition:03d}.json"
        (loader / f"repetition-{repetition:03d}.json").write_bytes(src.read_bytes())
    loaded = load_captured_repetitions(loader, campaign.census)
    assert len(loaded) == 3
    assert all(len(item) == 73 for item in loaded)


def test_acquisition_modules_do_not_import_private_gold() -> None:
    root = ROOT / "src/my_pa/application"
    for name in (
        "goodnotes_gsqs_b0_acquisition.py",
        "goodnotes_gsqs_b0_capture.py",
        "goodnotes_gsqs_b0_orchestrator.py",
        "goodnotes_gsqs_b0_model_client.py",
        "goodnotes_gsqs_b0_stdio_session.py",
        "goodnotes_gsqs_b0_synthetic_campaign.py",
    ):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not any("evaluator_binding" in item for item in imported)
        assert not any("controlled_handwriting" in item for item in imported)


def test_acquire_repetition_cli_does_not_score() -> None:
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    func = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_acquire_repetition"
    )
    names = {node.id for node in ast.walk(func) if isinstance(node, ast.Name)}
    assert "execute_measured_b0" not in names
    assert "score_partition" not in names
    assert "aggregate_b0_measurements" not in names


def test_stdio_startup_failure(tmp_path: Path) -> None:
    session = StdioEvalSession(
        command=["python3", "-c", "raise SystemExit(1)"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "src")},
        evidence_dir=tmp_path,
        timeout_seconds=2.0,
    )
    with pytest.raises(StdioHostError, match="stdio server failed startup"):
        session.initialize_and_list_tools()
    session.close()


def test_stdio_host_acquires_two_synthetic_cases(tmp_path: Path) -> None:
    campaign = build_synthetic_campaign(tmp_path / "campaign", case_count=2)
    auth = _write_auth(tmp_path, campaign)
    code = cli.main(
        [
            "acquire-repetition",
            "--authorization",
            str(auth),
            "--repetition",
            "1",
            "--output",
            str(tmp_path / "out"),
            "--campaign-fixture",
            str(tmp_path / "campaign" / "campaign.json"),
            "--raster-root",
            str(campaign.raster_root),
            "--repository-root",
            str(ROOT),
            "--model-client",
            MODEL_CLIENT_SYNTHETIC,
        ]
    )
    assert code == 0
    capture = tmp_path / "out" / "repetition-001.json"
    payload = json.loads(capture.read_text(encoding="utf-8"))
    assert payload["schema_version"] == CAPTURE_SCHEMA_VERSION
    assert [item["case_id"] for item in payload["documents"]] == [
        "synth-b0-001",
        "synth-b0-002",
    ]


def test_parser_exposes_acquire_repetition() -> None:
    parsed = cli.build_parser().parse_args(
        [
            "acquire-repetition",
            "--authorization",
            "auth.json",
            "--repetition",
            "1",
            "--output",
            "out",
            "--campaign-fixture",
            "campaign.json",
        ]
    )
    assert parsed.command == "acquire-repetition"
    assert parsed.repetition == 1
    serve = cli.build_parser().parse_args(
        ["serve-eval-mcp", "--authorization", "auth.json", "--campaign-fixture", "campaign.json"]
    )
    assert serve.campaign_fixture == "campaign.json"
