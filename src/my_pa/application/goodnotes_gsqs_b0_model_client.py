"""Narrow B0 model-client boundary. No ChatLLM UI, no gold, no silent fallback."""

from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from my_pa.application.goodnotes_gsqs_live_b0 import AnalyzerCaseInput, FrozenAnalyzerConfig
from my_pa.application.goodnotes_gsqs_routellm_envelope import assemble_authoritative_interchange

SYNTHETIC_CLIENT_IDENTITY = "synthetic-fake"
ROUTELLM_HTTP_CLIENT_IDENTITY = "routellm-http"
ROUTELLM_ACTIVATION_BLOCKER = "BLOCKED_ROUTELLM_CLIENT_ACTIVATION_AUTHORIZATION_REQUIRED"


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
    def __init__(self) -> None:
        super().__init__(
            ROUTELLM_ACTIVATION_BLOCKER,
            error_class="ROUTELLM_ACTIVATION_REQUIRED",
        )


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
    """Not activated. Direct RouteLLM HTTP remains uncommissioned."""

    identity = ROUTELLM_HTTP_CLIENT_IDENTITY

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RouteLLMClientActivationError()

    def session_id(self) -> str:
        raise RouteLLMClientActivationError()

    def analyze(self, case: AnalyzerCaseInput, config: FrozenAnalyzerConfig) -> dict[str, object]:
        del case, config
        raise RouteLLMClientActivationError()


def bind_model_client(identity: str) -> B0ModelClient:
    if identity == SYNTHETIC_CLIENT_IDENTITY:
        return SyntheticB0ModelClient()
    if identity == ROUTELLM_HTTP_CLIENT_IDENTITY:
        return RouteLLMHttpB0ModelClient()
    raise B0ModelClientError(f"unknown model-client {identity}", error_class="UNKNOWN_CLIENT")
