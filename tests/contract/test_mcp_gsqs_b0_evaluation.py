"""Evaluation MCP serves work/content ImageContent and withholds propose.

In-process stdio composition. Synthetic PNG only. RouteLLM HTTP stays dark.
Live NAS MCP is not used.
"""

from __future__ import annotations

import hashlib
import json
from base64 import b64decode
from datetime import UTC, datetime

import pytest
from tests.conftest import DEFAULT_LIMITS, WHEN, Scene, _staged_gray_png
from tests.contract.test_transport_parity import a_permitted_purpose, document
from tests.transports import mcp_transport

import my_pa.infrastructure.gsqs_routellm_transport as routellm
from my_pa.adapters.mcp.server import McpAccess
from my_pa.application.goodnotes_gsqs_b0_mcp import (
    EVALUATION_MCP_PURPOSES,
    EVALUATION_MCP_TOOLS,
    evaluation_handle,
    pin_evaluation_raster,
)
from my_pa.application.goodnotes_gsqs_live_b0 import B0CensusMember
from my_pa.application.service import ApplicationService
from my_pa.domain.identity.operation import Capability
from my_pa.infrastructure.gsqs_b0_evaluation import GsqsB0EvaluationUnitOfWork


def _image_blocks(result: object) -> list:
    return [b for b in result.content if getattr(b, "type", None) == "image"]


def test_evaluation_mcp_image_content_and_propose_refused(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    invoked: list[object] = []

    def forbidden(*_args: object, **_kwargs: object) -> object:
        invoked.append((_args, _kwargs))
        raise AssertionError("RouteLLM HTTP must not be invoked")

    monkeypatch.setattr(routellm, "post_chat_completion", forbidden)
    monkeypatch.setattr("urllib.request.urlopen", forbidden)

    png = _staged_gray_png()
    digest = hashlib.sha256(png).hexdigest()
    member = B0CensusMember(
        case_id="eval-case-a",
        raster_sha256=digest,
        case_digest="aa" * 32,
        file_sha256=digest,
    )
    work = evaluation_handle(member, principal_id=scene.principal.principal_id)
    raster = pin_evaluation_raster(work, png, created_at=datetime(2026, 8, 22, tzinfo=UTC))
    pages = ((work, raster),)
    service = ApplicationService(
        unit_of_work=lambda: GsqsB0EvaluationUnitOfWork(pages),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        managed_store=None,
        relationship_intelligence_enabled=False,
    )
    access = McpAccess(
        scene.principal,
        allowed_tools=EVALUATION_MCP_TOOLS,
        allowed_capability_purposes=EVALUATION_MCP_PURPOSES,
    )
    with mcp_transport(service, scene.principal, access_for_request=lambda _ctx: access) as session:
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
                    "idempotency_key": "eval-propose-refused-0001",
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

    assert Capability.GOODNOTES_WORK.value in listed
    assert Capability.GOODNOTES_CONTENT.value in listed
    assert Capability.GOODNOTES_PROPOSE.value not in listed
    assert work_result.is_error is False
    assert _image_blocks(work_result) == []
    assert content_result.is_error is False
    assert len(content_result.content) == 2
    image = content_result.content[1]
    assert image.type == "image"
    assert image.mime_type == "image/png"
    payload = json.loads(content_result.content[0].text)["result"]
    decoded = b64decode(image.data)
    assert decoded.startswith(b"\x89PNG")
    assert hashlib.sha256(decoded).hexdigest() == payload["digest"]
    assert propose_result.is_error is True
    assert _image_blocks(propose_result) == []
    assert invoked == []
