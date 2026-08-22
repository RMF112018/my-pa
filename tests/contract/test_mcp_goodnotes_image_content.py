"""MCP GoodNotes raster successes carry ImageContent; nothing else does.

Stdio composition over the SDK's in-memory streams. Synthetic fixtures only:
no live RouteLLM HTTP, no B0, and no live GoodNotes page.
"""

from __future__ import annotations

import hashlib
import json
from base64 import b64decode
from contextlib import AbstractContextManager

import pytest
from mcp.types import CallToolResult
from tests.conftest import (
    Scene,
    build_service,
    staged_goodnotes_raster,
    staged_goodnotes_work,
)
from tests.contract.test_transport_parity import a_permitted_purpose, document
from tests.transports import McpTransport, mcp_transport

from my_pa.application.commands import Representation
from my_pa.domain.identity.operation import Capability

type Served = AbstractContextManager[McpTransport]


def _image_blocks(result: CallToolResult) -> list:
    return [b for b in result.content if getattr(b, "type", None) == "image"]


def _assert_text_only(result: CallToolResult) -> None:
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert _image_blocks(result) == []


@pytest.fixture
def served(scene: Scene) -> Served[McpTransport]:
    """One initialized MCP session with a staged raster ready to disclose."""
    staged_goodnotes_work(scene)
    staged_goodnotes_raster(scene)
    return mcp_transport(build_service(scene.world, scene.providers), scene.principal)


def _content_document(scene: Scene, *, content_sha256: str | None = None) -> dict[str, object]:
    work = staged_goodnotes_work(scene)
    raster = staged_goodnotes_raster(scene)
    return document(
        Capability.GOODNOTES_CONTENT,
        scene.principal.principal_id,
        {
            "run_id": raster.run_id,
            "page_version_id": raster.page_version_id,
            "content_sha256": content_sha256 or work.content_sha256,
        },
        purpose=a_permitted_purpose(Capability.GOODNOTES_CONTENT),
    )


def test_goodnotes_content_appends_image_content_after_the_text_envelope(
    served: Served[McpTransport],
    scene: Scene,
) -> None:
    """A pinned PNG is the second block; the envelope stays first and canonical."""
    work = staged_goodnotes_work(scene)
    raster = staged_goodnotes_raster(scene)
    with served as session:
        result = session.call(Capability.GOODNOTES_CONTENT.value, _content_document(scene))
    assert result.is_error is False
    assert len(result.content) == 2
    assert result.content[0].type == "text"
    envelope = json.loads(result.content[0].text)
    payload = envelope["result"]
    assert payload["media_type"] == "image/png"
    assert payload["exact_render_sha256"]
    assert payload["exact_render_sha256"] == raster.exact_render_sha256
    assert "path" not in payload
    image = result.content[1]
    assert image.type == "image"
    assert _image_blocks(result) == [image]
    assert image.mime_type == "image/png"
    assert payload["content_base64"] == image.data
    png = b64decode(image.data)
    assert hashlib.sha256(png).hexdigest() == payload["digest"]
    assert len(png) == payload["byte_length"]
    assert png.startswith(b"\x89PNG")
    assert getattr(result, "structured_content", None) is None
    assert getattr(image, "meta", None) is None
    assert work.content_sha256 == payload["content_sha256"]


def test_non_raster_and_failure_calls_stay_text_only(
    served: Served[McpTransport],
    scene: Scene,
) -> None:
    """Work, propose, fetch, discovery, and refusals never grow an image block."""
    work = staged_goodnotes_work(scene)
    with served as session:
        work_result = session.call(
            Capability.GOODNOTES_WORK.value,
            document(
                Capability.GOODNOTES_WORK,
                scene.principal.principal_id,
                {"run_id": work.run_id, "page_version_id": work.page_version_id},
                purpose=a_permitted_purpose(Capability.GOODNOTES_WORK),
            ),
        )
        propose_result = session.call(
            Capability.GOODNOTES_PROPOSE.value,
            document(
                Capability.GOODNOTES_PROPOSE,
                scene.principal.principal_id,
                {
                    "run_id": work.run_id,
                    "page_version_id": work.page_version_id,
                    "content_sha256": work.content_sha256,
                    "schema_version": "note-unit.v1",
                    "analyzer_name": "synthetic",
                    "analyzer_version": "1",
                    "idempotency_key": "image-content-propose-v1-0001",
                    "segments": [
                        {
                            "kind": "NOTE_UNIT",
                            "geometry": {
                                "x_min": 0.1,
                                "y_min": 0.1,
                                "width": 0.2,
                                "height": 0.2,
                            },
                            "transcription": "synthetic note",
                            "primary_class": "MEETING",
                        }
                    ],
                },
                purpose=a_permitted_purpose(Capability.GOODNOTES_PROPOSE),
            ),
        )
        mismatch = session.call(
            Capability.GOODNOTES_CONTENT.value,
            _content_document(scene, content_sha256="b" * 64),
        )
        unknown = session.call("sources.destroy", {})
        malformed = session.call(Capability.GOODNOTES_CONTENT.value, {"payload": []})
        capabilities = session.call(
            Capability.CAPABILITIES_GET.value,
            document(
                Capability.CAPABILITIES_GET,
                scene.principal.principal_id,
                {},
                purpose=a_permitted_purpose(Capability.CAPABILITIES_GET),
            ),
        )
        fetched = session.call(
            Capability.SOURCES_FETCH.value,
            document(
                Capability.SOURCES_FETCH,
                scene.principal.principal_id,
                {
                    "source_id": scene.source.source_id,
                    "source_object_id": scene.markdown.source_object_id,
                    "representation": Representation.RAW_BYTES.value,
                    "max_bytes": 4096,
                },
                purpose=a_permitted_purpose(Capability.SOURCES_FETCH),
            ),
        )
    assert work_result.is_error is False
    _assert_text_only(work_result)
    handle = json.loads(work_result.content[0].text)["result"]
    assert handle["content_sha256"] == work.content_sha256
    assert "content_base64" not in handle

    assert propose_result.is_error is False
    _assert_text_only(propose_result)
    receipt = json.loads(propose_result.content[0].text)["result"]
    assert receipt["proposal_id"]

    assert mismatch.is_error is True
    _assert_text_only(mismatch)

    assert unknown.is_error is True
    _assert_text_only(unknown)

    assert malformed.is_error is True
    _assert_text_only(malformed)

    assert capabilities.is_error is False
    _assert_text_only(capabilities)
    assert len(capabilities.content) == 1

    assert fetched.is_error is False
    _assert_text_only(fetched)
    raw = json.loads(fetched.content[0].text)["result"]
    assert raw["content_base64"]
    assert raw["media_type"]
    assert "byte_count" in raw
    assert "exact_render_sha256" not in raw


def test_a_disabled_surface_refuses_content_without_an_image(scene: Scene) -> None:
    """The kill switch refuses before invoke and still answers with one text block."""
    staged_goodnotes_work(scene)
    staged_goodnotes_raster(scene)
    with mcp_transport(
        build_service(scene.world, scene.providers), scene.principal, enabled=False
    ) as session:
        result = session.call(Capability.GOODNOTES_CONTENT.value, _content_document(scene))
    assert result.is_error is True
    _assert_text_only(result)
