"""Narrow B0 model-client boundary. No ChatLLM UI, no gold, no silent fallback."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from my_pa.application.goodnotes_gsqs_live_b0 import AnalyzerCaseInput, FrozenAnalyzerConfig
from my_pa.application.goodnotes_gsqs_routellm_envelope import (
    assemble_authoritative_interchange,
    build_chat_completions_body,
    detect_image_mime,
    parse_semantic_content,
)

if TYPE_CHECKING:
    from my_pa.application.goodnotes_gsqs_b0_routellm_activation import RouteLLMClientActivation

SYNTHETIC_CLIENT_IDENTITY = "synthetic-fake"
ROUTELLM_HTTP_CLIENT_IDENTITY = "routellm-http"
ROUTELLM_ACTIVATION_BLOCKER = "BLOCKED_ROUTELLM_CLIENT_ACTIVATION_AUTHORIZATION_REQUIRED"
ROUTELLM_BASE_URL_ENV = "MY_PA_ROUTELLM_BASE_URL"
ROUTELLM_API_KEY_ENV = "MY_PA_ROUTELLM_API_KEY"
_DEFAULT_SELECTED_MODEL = "route-llm"


class B0ModelClient(Protocol):
    identity: str

    def session_id(self) -> str: ...

    def analyze(
        self, case: AnalyzerCaseInput, config: FrozenAnalyzerConfig
    ) -> dict[str, object]: ...


class B0ModelClientError(ValueError):
    """Model-client refusal or timeout."""

    error_class: str = "MODEL_CLIENT"

    def __init__(self, message: str, *, error_class: str = "MODEL_CLIENT") -> None:
        super().__init__(message)
        self.error_class = error_class


class RouteLLMClientActivationError(B0ModelClientError):
    def __init__(
        self,
        message: str = ROUTELLM_ACTIVATION_BLOCKER,
        *,
        error_class: str = "ROUTELLM_ACTIVATION_REQUIRED",
    ) -> None:
        super().__init__(message, error_class=error_class)


class SyntheticB0ModelClient:
    """Deterministic fake. Does not read gold or RouteLLM HTTP."""

    identity = SYNTHETIC_CLIENT_IDENTITY

    def __init__(self, *, request_timeout_seconds: float = 30.0) -> None:
        self._session_id = f"synth-{uuid4().hex}"
        self._timeout = request_timeout_seconds
        self._calls = 0

    def session_id(self) -> str:
        return self._session_id

    def analyze(self, case: AnalyzerCaseInput, config: FrozenAnalyzerConfig) -> dict[str, object]:
        self._calls += 1
        if not case.image_bytes:
            raise B0ModelClientError("image bytes required", error_class="MISSING_IMAGE")
        if config.model_identity == "":
            raise B0ModelClientError("model identity drift", error_class="MODEL_IDENTITY")
        semantic = {
            "segments": [
                {
                    "candidate_tags": [],
                    "geometry": {"height": 0.1, "width": 0.3, "x_min": 0.1, "y_min": 0.2},
                    "kind": "NOTE_UNIT",
                    "primary_class": "GENERAL",
                    "ranked_candidates": [],
                    "transcription": f"synthetic {case.case_id}",
                    "transcription_status": "CLEAR",
                }
            ]
        }
        return assemble_authoritative_interchange(
            case,
            config,
            semantic,
            provenance={
                "model_client": self.identity,
                "model_client_session_id": self._session_id,
                "model_client_request_id": f"{self._session_id}:{self._calls:03d}",
                "selected_model": "synthetic-fake",
            },
        )


class TimeoutB0ModelClient(SyntheticB0ModelClient):
    def analyze(self, case: AnalyzerCaseInput, config: FrozenAnalyzerConfig) -> dict[str, object]:
        del case, config
        raise B0ModelClientError("analyzer/model timeout", error_class="TIMEOUT")


class RouteLLMHttpB0ModelClient:
    """HISTORICAL_ONLY internal RouteLLM HTTP client.

    Production GSQS B0 is ChatLLM-client-driven and must not instantiate this
    client. Unit tests of the dormant HTTP path may still construct it.
    """

    identity = ROUTELLM_HTTP_CLIENT_IDENTITY

    def __init__(
        self,
        *,
        activation: RouteLLMClientActivation,
        origin: str | None = None,
        api_key: str | None = None,
        poster: Callable[..., Any] | None = None,
    ) -> None:
        from my_pa.application.goodnotes_gsqs_b0_routellm_activation import (
            admit_activation,
            origins_equal,
            parse_https_origin,
        )

        admit_activation(
            activation,
            expected_commit=activation.repository_commit,
            expected_tree=activation.repository_tree,
            expected_candidate=activation.candidate_identity,
            expected_prompt=activation.prompt_config_identity,
            expected_analyzer_name=activation.analyzer_name,
            expected_analyzer_version=activation.analyzer_version,
        )
        resolved_origin = (
            origin if origin is not None else os.environ.get(ROUTELLM_BASE_URL_ENV, "")
        )
        resolved_key = api_key if api_key is not None else os.environ.get(ROUTELLM_API_KEY_ENV, "")
        if not resolved_origin:
            raise B0ModelClientError("RouteLLM base URL is missing", error_class="MISSING_BASE_URL")
        if not resolved_key:
            raise B0ModelClientError("RouteLLM API key is missing", error_class="MISSING_API_KEY")
        runtime_origin = parse_https_origin(resolved_origin)
        if not origins_equal(activation.route_llm_endpoint_origin, runtime_origin):
            raise B0ModelClientError(
                "RouteLLM origin does not match activation", error_class="ORIGIN_MISMATCH"
            )
        self._activation = activation
        self._origin = runtime_origin
        self._api_key = resolved_key
        self._poster = poster
        self._session_id = f"routellm-{uuid4().hex}"
        self._calls = 0

    def session_id(self) -> str:
        return self._session_id

    def analyze(self, case: AnalyzerCaseInput, config: FrozenAnalyzerConfig) -> dict[str, object]:
        if config.model_identity != self._activation.model_identity:
            raise B0ModelClientError("model identity drift", error_class="MODEL_IDENTITY")
        if config.prompt_config_identity != self._activation.prompt_config_identity:
            raise B0ModelClientError("prompt identity drift", error_class="PROMPT_IDENTITY")
        if not case.image_bytes:
            raise B0ModelClientError("image bytes required", error_class="MISSING_IMAGE")
        if self._poster is None:
            raise B0ModelClientError("RouteLLM poster is missing", error_class="MISSING_POSTER")
        mime = detect_image_mime(case.image_bytes)
        body = build_chat_completions_body(case, config, image_bytes=case.image_bytes, mime=mime)
        try:
            result = self._poster(origin=self._origin, api_key=self._api_key, body=body)
        except B0ModelClientError:
            raise
        except Exception as error:
            error_class = getattr(error, "error_class", None)
            if isinstance(error_class, str) and error_class:
                raise B0ModelClientError(
                    "routellm request failed", error_class=error_class
                ) from error
            raise B0ModelClientError(
                "routellm request failed", error_class="MODEL_CLIENT"
            ) from error
        payload = result.payload if not isinstance(result, Mapping) else result
        if not isinstance(payload, Mapping):
            raise B0ModelClientError("routellm request failed", error_class="MALFORMED_JSON")
        try:
            semantic = parse_semantic_content(payload)
        except ValueError as error:
            raise B0ModelClientError(
                "malformed semantic content", error_class="MALFORMED_SEMANTIC"
            ) from error
        observed = payload.get("model")
        selected = observed if isinstance(observed, str) and observed else _DEFAULT_SELECTED_MODEL
        self._calls += 1
        return assemble_authoritative_interchange(
            case,
            config,
            semantic,
            provenance={
                "model_client": self.identity,
                "model_client_session_id": self._session_id,
                "model_client_request_id": f"{self._session_id}:{self._calls:03d}",
                "selected_model": selected,
            },
        )


def bind_model_client(
    identity: str,
    *,
    activation: RouteLLMClientActivation | None = None,
) -> B0ModelClient:
    if identity == SYNTHETIC_CLIENT_IDENTITY:
        return SyntheticB0ModelClient()
    if identity == ROUTELLM_HTTP_CLIENT_IDENTITY:
        if activation is None:
            raise RouteLLMClientActivationError()
        return RouteLLMHttpB0ModelClient(activation=activation)
    raise B0ModelClientError(f"unknown model-client {identity}", error_class="UNKNOWN_CLIENT")
