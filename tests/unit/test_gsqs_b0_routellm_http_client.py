"""Internal RouteLLM HTTP B0 client. Mock transport only."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs_b0_capture import (
    CaptureWriterError,
    capture_payload,
    write_repetition_capture,
)
from my_pa.application.goodnotes_gsqs_b0_model_client import (
    ROUTELLM_ACTIVATION_BLOCKER,
    B0ModelClientError,
    RouteLLMClientActivationError,
    RouteLLMHttpB0ModelClient,
    SyntheticB0ModelClient,
    bind_model_client,
)
from my_pa.application.goodnotes_gsqs_b0_synthetic_campaign import build_synthetic_campaign
from my_pa.application.goodnotes_gsqs_harness import INTERCHANGE_SCHEMA_VERSION
from my_pa.application.goodnotes_gsqs_live_b0 import AnalyzerCaseInput, FrozenAnalyzerConfig
from my_pa.infrastructure.gsqs_routellm_transport import (
    RouteLLMHttpResult,
    RouteLLMTransportError,
)
from tests.unit.test_gsqs_b0_local_execution import _binding, _identities
from tests.unit.test_gsqs_b0_routellm_activation import load_valid_activation

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
SENTINEL_KEY = "TEST-SENTINEL-API-KEY-NOT-A-SECRET"
RASTER_SENTINEL = b"\x89PNG\r\n\x1a\nRASTER-SENTINEL-BYTES-NOT-LOGGED" + b"\x00" * 8
ORIGIN = "https://route.example"


def _segments(case_id: str) -> dict[str, object]:
    return {
        "segments": [
            {
                "candidate_tags": [],
                "geometry": {"height": 0.1, "width": 0.3, "x_min": 0.1, "y_min": 0.2},
                "kind": "NOTE_UNIT",
                "primary_class": "GENERAL",
                "ranked_candidates": [],
                "transcription": f"synthetic {case_id}",
                "transcription_status": "CLEAR",
            }
        ]
    }


def _success_payload(case_id: str = "case-1", *, model: str = "route-llm") -> dict[str, object]:
    return {
        "choices": [{"message": {"content": json.dumps(_segments(case_id))}}],
        "model": model,
    }


def _case(*, case_id: str = "case-1", image_bytes: bytes | None = PNG) -> AnalyzerCaseInput:
    return AnalyzerCaseInput(
        case_id=case_id,
        corpus_version="gsqs-synthetic-b0-v1",
        raster_sha256="ab" * 32,
        interchange_schema_version=INTERCHANGE_SCHEMA_VERSION,
        image_bytes=image_bytes,
    )


def _config() -> FrozenAnalyzerConfig:
    identity, prompt, config = _identities()
    del identity, prompt
    return config


def _client(
    tmp_path: Path,
    *,
    poster: Callable[..., RouteLLMHttpResult] | None = None,
    origin: str | None = ORIGIN,
    api_key: str | None = SENTINEL_KEY,
    **activation_overrides: object,
) -> RouteLLMHttpB0ModelClient:
    activation = load_valid_activation(tmp_path, **activation_overrides)
    return RouteLLMHttpB0ModelClient(
        activation=activation,
        origin=origin,
        api_key=api_key,
        poster=poster,
    )


def _assert_secret_free(payload: object) -> None:
    text = str(payload)
    assert SENTINEL_KEY not in text
    assert "Authorization" not in text
    assert "data:image" not in text
    assert RASTER_SENTINEL.decode("latin1") not in text


def test_bind_without_activation_fails_closed() -> None:
    with pytest.raises(RouteLLMClientActivationError, match=ROUTELLM_ACTIVATION_BLOCKER):
        bind_model_client("routellm-http")


def test_missing_base_url_and_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MY_PA_ROUTELLM_BASE_URL", raising=False)
    monkeypatch.delenv("MY_PA_ROUTELLM_API_KEY", raising=False)
    activation = load_valid_activation(tmp_path)
    with pytest.raises(B0ModelClientError) as raised:
        RouteLLMHttpB0ModelClient(
            activation=activation, api_key=SENTINEL_KEY, poster=lambda **_: None
        )
    assert raised.value.error_class == "MISSING_BASE_URL"
    _assert_secret_free(raised.value)
    with pytest.raises(B0ModelClientError) as raised:
        RouteLLMHttpB0ModelClient(activation=activation, origin=ORIGIN, poster=lambda **_: None)
    assert raised.value.error_class == "MISSING_API_KEY"
    _assert_secret_free(raised.value)
    _assert_secret_free(repr(raised.value))


def test_non_https_origin_and_origin_mismatch(tmp_path: Path) -> None:
    with pytest.raises(B0ModelClientError) as raised:
        _client(tmp_path / "http", origin="http://route.example")
    assert raised.value.error_class in {"NON_HTTPS_ORIGIN", "ORIGIN_MISMATCH"}
    _assert_secret_free(raised.value)
    with pytest.raises(B0ModelClientError) as raised:
        _client(tmp_path / "other", origin="https://other.example")
    assert raised.value.error_class == "ORIGIN_MISMATCH"
    _assert_secret_free(raised.value)


def test_analyze_identity_and_missing_image(tmp_path: Path) -> None:
    client = _client(tmp_path, poster=lambda **_: RouteLLMHttpResult(200, _success_payload()))
    config = _config()
    with pytest.raises(B0ModelClientError) as raised:
        client.analyze(_case(image_bytes=b""), config)
    assert raised.value.error_class == "MISSING_IMAGE"
    drifted = FrozenAnalyzerConfig(
        analyzer_name=config.analyzer_name,
        analyzer_version=config.analyzer_version,
        model_identity="other-model",
        prompt_config_identity=config.prompt_config_identity,
        prompt_text=config.prompt_text,
    )
    with pytest.raises(B0ModelClientError) as raised:
        client.analyze(_case(), drifted)
    assert raised.value.error_class == "MODEL_IDENTITY"
    drifted_prompt = FrozenAnalyzerConfig(
        analyzer_name=config.analyzer_name,
        analyzer_version=config.analyzer_version,
        model_identity=config.model_identity,
        prompt_config_identity="other-prompt",
        prompt_text=config.prompt_text,
    )
    with pytest.raises(B0ModelClientError) as raised:
        client.analyze(_case(), drifted_prompt)
    assert raised.value.error_class == "PROMPT_IDENTITY"


@pytest.mark.parametrize(
    ("error_class", "http_status"),
    [
        ("HTTP_401", 401),
        ("HTTP_403", 403),
        ("HTTP_404", 404),
        ("HTTP_408", 408),
        ("HTTP_429", 429),
        ("HTTP_500", 500),
        ("REDIRECT", None),
        ("URL_ERROR", None),
        ("TIMEOUT", None),
        ("RESPONSE_TOO_LARGE", None),
        ("MALFORMED_JSON", None),
    ],
)
def test_transport_errors_are_mapped(
    tmp_path: Path, error_class: str, http_status: int | None, caplog: pytest.LogCaptureFixture
) -> None:
    def poster(**_kwargs: object) -> RouteLLMHttpResult:
        raise RouteLLMTransportError(
            "routellm request failed",
            http_status=http_status,
            error_class=error_class,
        )

    client = _client(tmp_path, poster=poster)
    with pytest.raises(B0ModelClientError) as raised:
        client.analyze(_case(image_bytes=RASTER_SENTINEL), _config())
    assert raised.value.error_class == error_class
    assert not isinstance(client, SyntheticB0ModelClient)
    _assert_secret_free(raised.value)
    _assert_secret_free(repr(raised.value))
    _assert_secret_free(caplog.text)


def test_malformed_semantic_is_mapped(tmp_path: Path) -> None:
    def poster(**_kwargs: object) -> RouteLLMHttpResult:
        return RouteLLMHttpResult(200, {"choices": [{"message": {"content": "not-json"}}]})

    client = _client(tmp_path, poster=poster)
    with pytest.raises(B0ModelClientError) as raised:
        client.analyze(_case(), _config())
    assert raised.value.error_class == "MALFORMED_SEMANTIC"


def test_poster_is_called_once_on_failure(tmp_path: Path) -> None:
    calls = {"n": 0}

    def poster(**_kwargs: object) -> RouteLLMHttpResult:
        calls["n"] += 1
        raise RouteLLMTransportError("routellm request failed", error_class="HTTP_500")

    client = _client(tmp_path, poster=poster)
    with pytest.raises(B0ModelClientError) as raised:
        client.analyze(_case(), _config())
    assert calls["n"] == 1
    assert raised.value.error_class == "HTTP_500"
    assert type(client) is RouteLLMHttpB0ModelClient


def test_observed_model_is_provenance_only(tmp_path: Path) -> None:
    def poster(**_kwargs: object) -> RouteLLMHttpResult:
        return RouteLLMHttpResult(200, _success_payload(model="some-other-observed-model"))

    client = _client(tmp_path, poster=poster)
    config = _config()
    document = client.analyze(_case(), config)
    assert document["model_identity"] == config.model_identity
    assert document["selected_model"] == "some-other-observed-model"
    assert document["model_client"] == "routellm-http"


def test_mock_commissioning_posts_once_and_captures(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[dict[str, object]] = []

    def poster(
        *, origin: str, api_key: str, body: dict[str, object], **_kwargs: object
    ) -> RouteLLMHttpResult:
        calls.append({"origin": origin, "api_key": api_key, "body": body})
        case_id = "synth-b0-001"
        return RouteLLMHttpResult(200, _success_payload(case_id))

    client = _client(tmp_path / "client", poster=poster)
    campaign = build_synthetic_campaign(tmp_path / "campaign", case_count=1)
    member = campaign.census.members[0]
    png = (campaign.raster_root / f"{member.case_id}.png").read_bytes()
    config = _config()
    document = client.analyze(
        AnalyzerCaseInput(
            case_id=member.case_id,
            corpus_version=campaign.corpus_version,
            raster_sha256=member.raster_sha256,
            interchange_schema_version=INTERCHANGE_SCHEMA_VERSION,
            image_bytes=png,
        ),
        config,
    )
    assert len(calls) == 1
    assert calls[0]["origin"] == ORIGIN
    body = calls[0]["body"]
    assert isinstance(body, dict)
    assert body["model"] == "route-llm"
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[0]["role"] == "system"
    assert config.prompt_text == messages[0]["content"]
    user = messages[1]["content"]
    assert isinstance(user, list)
    image = user[1]["image_url"]["url"]
    assert image.startswith("data:image/png;base64,")
    dumped = json.dumps(document)
    assert "gold" not in dumped.lower()
    assert "expected_score" not in dumped
    written = write_repetition_capture(
        tmp_path / "out",
        binding=_binding(campaign),
        census=campaign.census,
        documents=[document],
    )
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "gsqs-analyzer-capture-v1"
    assert "gold" not in json.dumps(payload).lower()
    with pytest.raises(CaptureWriterError, match="gold"):
        capture_payload(
            binding=_binding(campaign),
            census=campaign.census,
            documents=[dict(document, gold="nope")],
        )
    _assert_secret_free(caplog.text)
    assert SENTINEL_KEY not in dumped
