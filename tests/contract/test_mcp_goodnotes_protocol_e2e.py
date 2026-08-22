"""One synthetic MCP session walks work → content → propose without RouteLLM.

Stdio composition over the SDK's in-memory streams. The raster is staged; no
B0 evaluator runs and no live GoodNotes page is opened.
"""

from __future__ import annotations

import hashlib
import json
from base64 import b64decode

import pytest
from tests.conftest import (
    Scene,
    build_service,
    staged_goodnotes_raster,
    staged_goodnotes_work,
)
from tests.contract.test_transport_parity import a_permitted_purpose, document
from tests.transports import mcp_transport

import my_pa.infrastructure.gsqs_routellm_transport as routellm
from my_pa.domain.identity.operation import Capability


def _image_blocks(result: object) -> list:
    return [b for b in result.content if getattr(b, "type", None) == "image"]


def test_work_content_propose_on_one_session_never_invokes_routellm_http(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Initialize, list, work, content, propose — and the HTTP transport stays dark."""
    invoked: list[object] = []

    def forbidden(*_args: object, **_kwargs: object) -> object:
        invoked.append((_args, _kwargs))
        raise AssertionError("RouteLLM HTTP must not be invoked")

    monkeypatch.setattr(routellm, "post_chat_completion", forbidden)
    monkeypatch.setattr("urllib.request.urlopen", forbidden)

    work = staged_goodnotes_work(scene)
    staged_goodnotes_raster(scene)
    with mcp_transport(build_service(scene.world, scene.providers), scene.principal) as session:
        handshake = session.initialize_result()
        listed = {tool.name for tool in session.list_tools().tools}
        work_result = session.call(
            Capability.GOODNOTES_WORK.value,
            document(
                Capability.GOODNOTES_WORK,
                scene.principal.principal_id,
                {"run_id": work.run_id, "page_version_id": work.page_version_id},
                purpose=a_permitted_purpose(Capability.GOODNOTES_WORK),
            ),
        )
        handle = json.loads(work_result.content[0].text)["result"]
        content_result = session.call(
            Capability.GOODNOTES_CONTENT.value,
            document(
                Capability.GOODNOTES_CONTENT,
                scene.principal.principal_id,
                {
                    "run_id": handle["run_id"],
                    "page_version_id": handle["page_version_id"],
                    "content_sha256": handle["content_sha256"],
                },
                purpose=a_permitted_purpose(Capability.GOODNOTES_CONTENT),
            ),
        )
        propose_result = session.call(
            Capability.GOODNOTES_PROPOSE.value,
            document(
                Capability.GOODNOTES_PROPOSE,
                scene.principal.principal_id,
                {
                    "run_id": handle["run_id"],
                    "page_version_id": handle["page_version_id"],
                    "content_sha256": handle["content_sha256"],
                    "schema_version": "note-unit.v2",
                    "analyzer_name": "synthetic",
                    "analyzer_version": "1",
                    "idempotency_key": "e2e-goodnotes-propose-v2-0001",
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
                            "ranked_candidates": [{"rank": 1, "candidate": "Alpha Project"}],
                            "candidate_tags": ["follow-up"],
                            "confidence": {"transcription": 0.9, "linking": 0.8},
                            "transcription_status": "CLEAR",
                        }
                    ],
                },
                purpose=a_permitted_purpose(Capability.GOODNOTES_PROPOSE),
            ),
        )

    assert handshake.server_info.name == "my-pa"
    assert {
        Capability.GOODNOTES_WORK.value,
        Capability.GOODNOTES_CONTENT.value,
        Capability.GOODNOTES_PROPOSE.value,
    } <= listed

    assert work_result.is_error is False
    assert work_result.content[0].type == "text"
    assert _image_blocks(work_result) == []
    assert handle["content_sha256"] == work.content_sha256
    assert handle["renderer_name"]
    assert handle["renderer_version"]
    assert handle["render_profile_version"]

    assert content_result.is_error is False
    assert len(content_result.content) == 2
    assert content_result.content[0].type == "text"
    envelope = json.loads(content_result.content[0].text)
    payload = envelope["result"]
    image = content_result.content[1]
    assert image.type == "image"
    assert image.mime_type == "image/png"
    assert payload["media_type"] == "image/png"
    assert payload["exact_render_sha256"]
    assert "path" not in payload
    assert payload["content_base64"] == image.data
    png = b64decode(image.data)
    assert png.startswith(b"\x89PNG")
    assert hashlib.sha256(png).hexdigest() == payload["digest"]
    assert len(png) == payload["byte_length"]

    assert propose_result.is_error is False
    assert propose_result.content[0].type == "text"
    assert _image_blocks(propose_result) == []
    receipt = json.loads(propose_result.content[0].text)["result"]
    assert receipt["proposal_id"]
    assert receipt["replayed"] is False

    assert invoked == []
