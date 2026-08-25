"""Bounded B0 prediction-acquisition authorization. No gold, no scoring.

Real handwriting remains fail-closed in this implementation. A correctly shaped
`REAL_HANDWRITING_B0_EXECUTION` artifact is recognized as the future gate and is
not admitted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from my_pa.application.goodnotes_gsqs_hw_corpus import HANDWRITING_CORPUS_VERSION
from my_pa.application.goodnotes_gsqs_live_b0 import APPROVED_COMBINED_IDENTITY

ACQUISITION_AUTH_SCHEMA = "gsqs-b0-acquisition-authorization-v1"
OPERATION_SYNTHETIC = "SYNTHETIC_B0_ACQUISITION"
OPERATION_REAL = "REAL_HANDWRITING_B0_EXECUTION"
CAMPAIGN_CLASS_SYNTHETIC = "SYNTHETIC"
CAMPAIGN_CLASS_REAL = "REAL_HANDWRITING"
MODEL_CLIENT_SYNTHETIC = "synthetic-fake"
MODEL_CLIENT_ROUTELLM_HTTP = "routellm-http"
REAL_HANDWRITING_ACQUISITION_ADMITTED = False


@dataclass(frozen=True, slots=True)
class AcquisitionAuthorization:
    schema_version: str
    authorization_id: str
    operation: str
    campaign_id: str
    campaign_class: str
    repetition: int
    corpus_version: str
    corpus_manifest_digest: str
    combined_identity: str
    candidate_identity: str
    model_identity: str
    prompt_config_identity: str
    analyzer_name: str
    analyzer_version: str
    model_client: str
    mcp_evaluation_surface: str
    mcp_evaluation_binding_mode: str
    mcp_evaluation_evidence_id: str


class AcquisitionError(ValueError):
    """Prediction acquisition refused before any raster was processed."""


def is_real_handwriting_campaign(*, corpus_version: str, combined_identity: str) -> bool:
    return (
        corpus_version == HANDWRITING_CORPUS_VERSION
        or combined_identity == APPROVED_COMBINED_IDENTITY
    )


def load_acquisition_authorization(path: Path) -> AcquisitionAuthorization:
    if path.is_symlink() or not path.is_file():
        raise AcquisitionError("acquisition authorization is missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AcquisitionError("acquisition authorization must be a JSON object")
    return acquisition_from_mapping(payload)


def acquisition_from_mapping(payload: dict[str, object]) -> AcquisitionAuthorization:
    auth = AcquisitionAuthorization(
        schema_version=_token(payload, "schema_version"),
        authorization_id=_token(payload, "authorization_id"),
        operation=_token(payload, "operation"),
        campaign_id=_token(payload, "campaign_id"),
        campaign_class=_token(payload, "campaign_class"),
        repetition=_int(payload, "repetition"),
        corpus_version=_token(payload, "corpus_version"),
        corpus_manifest_digest=_token(payload, "corpus_manifest_digest"),
        combined_identity=_token(payload, "combined_identity"),
        candidate_identity=_token(payload, "candidate_identity"),
        model_identity=_token(payload, "model_identity"),
        prompt_config_identity=_token(payload, "prompt_config_identity"),
        analyzer_name=_token(payload, "analyzer_name"),
        analyzer_version=_token(payload, "analyzer_version"),
        model_client=_token(payload, "model_client"),
        mcp_evaluation_surface=_token(payload, "mcp_evaluation_surface"),
        mcp_evaluation_binding_mode=_token(payload, "mcp_evaluation_binding_mode"),
        mcp_evaluation_evidence_id=_token(payload, "mcp_evaluation_evidence_id"),
    )
    if auth.schema_version != ACQUISITION_AUTH_SCHEMA:
        raise AcquisitionError("wrong acquisition authorization schema")
    if auth.repetition < 1:
        raise AcquisitionError("repetition must be >= 1")
    return auth


def assert_acquisition_permitted(
    authorization: AcquisitionAuthorization,
    *,
    repetition: int,
    corpus_version: str,
    combined_identity: str,
    model_identity: str,
    prompt_config_identity: str,
    candidate_identity: str,
    model_client: str,
) -> None:
    real = is_real_handwriting_campaign(
        corpus_version=corpus_version, combined_identity=combined_identity
    )
    if real or authorization.campaign_class == CAMPAIGN_CLASS_REAL:
        if authorization.operation != OPERATION_REAL:
            raise AcquisitionError(
                "frozen real handwriting corpus requires REAL_HANDWRITING_B0_EXECUTION"
            )
        if not REAL_HANDWRITING_ACQUISITION_ADMITTED:
            raise AcquisitionError(
                "REAL_HANDWRITING_B0_EXECUTION is not admitted in this implementation"
            )
    elif authorization.operation != OPERATION_SYNTHETIC:
        raise AcquisitionError("synthetic acquisition requires SYNTHETIC_B0_ACQUISITION")
    elif authorization.campaign_class != CAMPAIGN_CLASS_SYNTHETIC:
        raise AcquisitionError("synthetic campaign_class required")
    if authorization.repetition != repetition:
        raise AcquisitionError("authorization repetition mismatch")
    if authorization.corpus_version != corpus_version:
        raise AcquisitionError("authorization corpus_version mismatch")
    if authorization.combined_identity != combined_identity:
        raise AcquisitionError("authorization combined_identity mismatch")
    if authorization.model_identity != model_identity:
        raise AcquisitionError("model identity drift")
    if authorization.prompt_config_identity != prompt_config_identity:
        raise AcquisitionError("prompt identity drift")
    if authorization.candidate_identity != candidate_identity:
        raise AcquisitionError("candidate identity mismatch")
    if authorization.model_client != model_client:
        raise AcquisitionError("model-client configuration mismatch")
    if real and authorization.model_client == MODEL_CLIENT_ROUTELLM_HTTP:
        raise AcquisitionError("RouteLLM HTTP client is not activated")


def _token(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or "\x00" in value:
        raise AcquisitionError(f"authorization missing {key}")
    return value


def _int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AcquisitionError(f"authorization missing {key}")
    return value
