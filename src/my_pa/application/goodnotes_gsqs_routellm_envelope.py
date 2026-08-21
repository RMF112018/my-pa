"""Local authoritative gsqs-analyzer-output-v1 envelope from untrusted semantics."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any, Protocol

from my_pa.application.goodnotes_gsqs_harness import INTERCHANGE_SCHEMA_VERSION
from my_pa.domain.goodnotes.models import NOTE_UNIT_SCHEMA_V2


class EnvelopeCase(Protocol):
    @property
    def case_id(self) -> str: ...

    @property
    def corpus_version(self) -> str: ...

    @property
    def raster_sha256(self) -> str: ...

    @property
    def interchange_schema_version(self) -> str: ...

    @property
    def image_bytes(self) -> bytes | None: ...


class EnvelopeConfig(Protocol):
    @property
    def analyzer_name(self) -> str: ...

    @property
    def analyzer_version(self) -> str: ...

    @property
    def model_identity(self) -> str: ...

    @property
    def prompt_config_identity(self) -> str: ...

    @property
    def prompt_text(self) -> str: ...


_TRUSTED_IDENTITY_KEYS = frozenset(
    {
        "analyzer_name",
        "analyzer_version",
        "case_id",
        "content_sha256",
        "corpus_version",
        "model_identity",
        "prompt_config_identity",
        "proposal_schema_version",
        "schema_version",
    }
)
_IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"RIFF", "webp"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


def detect_image_mime(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "webp"
    for prefix, mime in _IMAGE_MAGIC:
        if prefix != b"RIFF" and image_bytes.startswith(prefix):
            return mime
    raise ValueError("unknown image MIME")


def extract_segments(semantic: object) -> list[object]:
    if not isinstance(semantic, Mapping):
        raise ValueError("semantic payload is not an object")
    segments = semantic.get("segments")
    if not isinstance(segments, list):
        raise ValueError("missing semantic segments")
    return list(segments)


def model_emitted_identity_fields(semantic: object) -> tuple[str, ...]:
    if not isinstance(semantic, Mapping):
        return ()
    return tuple(sorted(key for key in semantic if key in _TRUSTED_IDENTITY_KEYS))


def assemble_authoritative_interchange(
    case: EnvelopeCase,
    config: EnvelopeConfig,
    semantic: object,
    *,
    provenance: Mapping[str, object] | None = None,
) -> dict[str, object]:
    document: dict[str, object] = {
        "analyzer_name": config.analyzer_name,
        "analyzer_version": config.analyzer_version,
        "case_id": case.case_id,
        "content_sha256": case.raster_sha256,
        "corpus_version": case.corpus_version,
        "model_identity": config.model_identity,
        "prompt_config_identity": config.prompt_config_identity,
        "proposal_schema_version": NOTE_UNIT_SCHEMA_V2,
        "schema_version": INTERCHANGE_SCHEMA_VERSION,
        "segments": extract_segments(semantic),
    }
    emitted = model_emitted_identity_fields(semantic)
    if emitted:
        document["model_emitted_identity_fields"] = list(emitted)
    if provenance:
        for key, value in provenance.items():
            if key in _TRUSTED_IDENTITY_KEYS:
                continue
            document[key] = value
    return document


def build_chat_completions_body(
    case: EnvelopeCase,
    config: EnvelopeConfig,
    *,
    image_bytes: bytes,
    mime: str,
) -> dict[str, Any]:
    if not image_bytes:
        raise ValueError("image bytes required")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    user_text = (
        "Analyze this handwriting page. Return JSON with a segments array only. "
        f"case_id={case.case_id} corpus_version={case.corpus_version} "
        f"raster_sha256={case.raster_sha256} "
        f"interchange_schema={case.interchange_schema_version}."
    )
    return {
        "messages": [
            {"content": config.prompt_text, "role": "system"},
            {
                "content": [
                    {"text": user_text, "type": "text"},
                    {
                        "image_url": {"url": f"data:image/{mime};base64,{encoded}"},
                        "type": "image_url",
                    },
                ],
                "role": "user",
            },
        ],
        "model": "route-llm",
    }


def parse_semantic_content(provider_payload: Mapping[str, object]) -> object:
    choices = provider_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("provider JSON missing choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise ValueError("provider choice is not an object")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("provider message missing")
    if first.get("finish_reason") == "tool_calls" or message.get("tool_calls"):
        raise ValueError("provider returned tool_calls")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("missing semantic content")
    try:
        parsed: object = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("malformed provider JSON") from error
    return parsed
