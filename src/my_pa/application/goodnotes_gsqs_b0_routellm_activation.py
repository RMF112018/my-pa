"""Activation artifact for the internal RouteLLM B0 client. No secrets, no gold."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from my_pa.application.goodnotes_gsqs_b0_acquisition import (
    CAMPAIGN_CLASS_SYNTHETIC,
    MODEL_CLIENT_ROUTELLM_HTTP,
)
from my_pa.application.goodnotes_gsqs_b0_model_client import B0ModelClientError

ACTIVATION_SCHEMA = "gsqs-b0-routellm-client-activation-v1"
ACTIVATION_OPERATION = "ACTIVATE_INTERNAL_ROUTELLM_B0_CLIENT"
ACTIVATION_PATH_ENV = "MY_PA_GSQS_B0_ROUTELLM_ACTIVATION"
FALLBACK_POLICY_NONE = "none"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_FORBIDDEN_FIELD_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "gold",
        "private_gold",
        "private_key",
        "token",
    }
)


class RouteLLMActivationError(B0ModelClientError):
    """Activation artifact refused. Message contains no secrets or rasters."""

    def __init__(self, message: str, *, error_class: str = "ACTIVATION") -> None:
        super().__init__(message, error_class=error_class)


@dataclass(frozen=True, slots=True)
class RouteLLMClientActivation:
    schema_version: str
    operation: str
    repository_commit: str
    repository_tree: str
    model_client: str
    candidate_identity: str
    model_identity: str
    prompt_config_identity: str
    analyzer_name: str
    analyzer_version: str
    campaign_class: str
    route_llm_endpoint_origin: str
    https_required: bool
    fallback_policy: str
    external_synthetic_commissioning_status: str
    real_handwriting_admitted: bool
    invalidation_rule: str


def parse_https_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RouteLLMActivationError(
            "RouteLLM origin must be an exact credential-free HTTPS origin",
            error_class="NON_HTTPS_ORIGIN",
        )
    host = parsed.hostname.lower()
    if parsed.port:
        return f"https://{host}:{parsed.port}"
    return f"https://{host}"


def origins_equal(authorized: str, runtime: str) -> bool:
    return parse_https_origin(authorized) == parse_https_origin(runtime)


def load_activation(path: Path) -> RouteLLMClientActivation:
    if path.is_symlink() or not path.is_file():
        raise RouteLLMActivationError("activation is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RouteLLMActivationError("activation is missing") from error
    if not isinstance(payload, dict):
        raise RouteLLMActivationError("activation must be a JSON object")
    _reject_forbidden_fields(payload)
    origin = parse_https_origin(_token(payload, "route_llm_endpoint_origin"))
    activation = RouteLLMClientActivation(
        schema_version=_token(payload, "schema_version"),
        operation=_token(payload, "operation"),
        repository_commit=_token(payload, "repository_commit"),
        repository_tree=_token(payload, "repository_tree"),
        model_client=_token(payload, "model_client"),
        candidate_identity=_token(payload, "candidate_identity"),
        model_identity=_token(payload, "model_identity"),
        prompt_config_identity=_token(payload, "prompt_config_identity"),
        analyzer_name=_token(payload, "analyzer_name"),
        analyzer_version=_token(payload, "analyzer_version"),
        campaign_class=_token(payload, "campaign_class"),
        route_llm_endpoint_origin=origin,
        https_required=_bool(payload, "https_required"),
        fallback_policy=_token(payload, "fallback_policy"),
        external_synthetic_commissioning_status=_token(
            payload, "external_synthetic_commissioning_status"
        ),
        real_handwriting_admitted=_bool(payload, "real_handwriting_admitted"),
        invalidation_rule=_token(payload, "invalidation_rule"),
    )
    if activation.schema_version != ACTIVATION_SCHEMA:
        raise RouteLLMActivationError("wrong activation schema", error_class="WRONG_SCHEMA")
    if activation.operation != ACTIVATION_OPERATION:
        raise RouteLLMActivationError("wrong activation operation")
    return activation


def admit_activation(
    activation: RouteLLMClientActivation,
    *,
    expected_commit: str,
    expected_tree: str,
    expected_candidate: str,
    expected_prompt: str,
    expected_analyzer_name: str,
    expected_analyzer_version: str,
) -> None:
    if not _HEX40.fullmatch(activation.repository_commit) or not _HEX40.fullmatch(
        activation.repository_tree
    ):
        raise RouteLLMActivationError(
            "implementation identity mismatch", error_class="IMPLEMENTATION_IDENTITY"
        )
    if not _HEX40.fullmatch(expected_commit) or not _HEX40.fullmatch(expected_tree):
        raise RouteLLMActivationError(
            "implementation identity mismatch", error_class="IMPLEMENTATION_IDENTITY"
        )
    if (
        activation.repository_commit != expected_commit
        or activation.repository_tree != expected_tree
    ):
        raise RouteLLMActivationError(
            "implementation identity mismatch", error_class="IMPLEMENTATION_IDENTITY"
        )
    if activation.schema_version != ACTIVATION_SCHEMA:
        raise RouteLLMActivationError("wrong activation schema", error_class="WRONG_SCHEMA")
    if activation.operation != ACTIVATION_OPERATION:
        raise RouteLLMActivationError("wrong activation operation")
    if activation.model_client != MODEL_CLIENT_ROUTELLM_HTTP:
        raise RouteLLMActivationError(
            "model-client configuration mismatch", error_class="MODEL_CLIENT_MISMATCH"
        )
    if activation.campaign_class != CAMPAIGN_CLASS_SYNTHETIC:
        raise RouteLLMActivationError("synthetic campaign_class required")
    if activation.https_required is not True:
        raise RouteLLMActivationError("https_required must be true")
    if activation.fallback_policy != FALLBACK_POLICY_NONE:
        raise RouteLLMActivationError("fallback_policy must be none")
    if activation.real_handwriting_admitted is not False:
        raise RouteLLMActivationError("real handwriting is not admitted")
    parse_https_origin(activation.route_llm_endpoint_origin)
    if activation.candidate_identity != expected_candidate:
        raise RouteLLMActivationError(
            "candidate identity mismatch", error_class="CANDIDATE_IDENTITY"
        )
    if activation.prompt_config_identity != expected_prompt:
        raise RouteLLMActivationError("prompt identity mismatch", error_class="PROMPT_IDENTITY")
    if activation.analyzer_name != expected_analyzer_name:
        raise RouteLLMActivationError("analyzer identity mismatch")
    if activation.analyzer_version != expected_analyzer_version:
        raise RouteLLMActivationError("analyzer identity mismatch")


def _reject_forbidden_fields(payload: object) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if lowered in _FORBIDDEN_FIELD_KEYS:
                raise RouteLLMActivationError("activation contains a forbidden field")
            _reject_forbidden_fields(value)
    elif isinstance(payload, list):
        for item in payload:
            _reject_forbidden_fields(item)


def _token(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or "\x00" in value:
        raise RouteLLMActivationError(f"activation missing {key}")
    return value


def _bool(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise RouteLLMActivationError(f"activation missing {key}")
    return value
