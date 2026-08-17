"""Synthetic GoodNotes Durable Note Intelligence Task canary.

Exercises ApplicationService.invoke and MCP tool descriptions for the proposed
regular Agent Task. Not a live Abacus OAuth, tools/list, Task create/edit, or
production invocation. Those remain operator-gated in
ops/runbooks/goodnotes-durable-note-intelligence.md.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import get_args

from tests.conftest import (
    Scene,
    build_service,
    metadata_for,
    operator,
    staged_goodnotes_raster,
    staged_goodnotes_work,
)
from tests.contract.test_application_capabilities import run, succeeded

from my_pa.adapters.mcp.tools import TOOLS
from my_pa.application.commands import (
    Command,
    GetGoodNotesContent,
    GetGoodNotesWork,
    SubmitGoodNotesProposal,
)
from my_pa.bootstrap import goodnotes as goodnotes_bootstrap
from my_pa.bootstrap.goodnotes import compose_local_goodnotes_runtime
from my_pa.bootstrap.goodnotes_durable_note import (
    ALLOWED_CAPABILITIES,
    DRAFT_STATUS,
    TASK_NAME,
    activated_task_capabilities,
    durable_note_task_is_activated,
    mcp_profile_refuses,
    profile_tool_names,
)
from my_pa.bootstrap.settings import ENV_PREFIX, Settings, load_settings
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.goodnotes.models import issue_stable_id
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "ops" / "abacus" / "goodnotes-durable-note-intelligence.task.json"
DSN = "postgresql+psycopg://my_pa@localhost:5433/my_pa_settings_probe"

WORK_TOOL = next(tool for tool in TOOLS if tool.name == Capability.GOODNOTES_WORK.value)
CONTENT_TOOL = next(tool for tool in TOOLS if tool.name == Capability.GOODNOTES_CONTENT.value)
PROPOSE_TOOL = next(tool for tool in TOOLS if tool.name == Capability.GOODNOTES_PROPOSE.value)
_COMMANDS = {member.capability: member for member in get_args(Command.__value__)}
PUBLISHED = frozenset(tool.name for tool in TOOLS)

FORBIDDEN_SUBSTITUTES = frozenset(
    {
        Capability.KNOWLEDGE_SEARCH.value,
        Capability.KNOWLEDGE_READ.value,
        Capability.CONTEXT_PREPARE.value,
        Capability.REVIEW_DECIDE.value,
        Capability.TASKS_CREATE.value,
        Capability.DOCUMENTS_CREATE.value,
    }
)


def _settings(**overrides: object) -> Settings:
    return Settings(database_url=DSN, **overrides)  # type: ignore[arg-type]


def _work(scene: Scene, command: GetGoodNotesWork) -> ResponseEnvelope:
    return run(
        build_service(scene.world, scene.providers),
        scene,
        Capability.GOODNOTES_WORK,
        Purpose.GOODNOTES_WORK,
        command,
    )


def _content(scene: Scene, command: GetGoodNotesContent) -> ResponseEnvelope:
    return run(
        build_service(scene.world, scene.providers),
        scene,
        Capability.GOODNOTES_CONTENT,
        Purpose.GOODNOTES_CONTENT,
        command,
    )


def _propose(scene: Scene, command: SubmitGoodNotesProposal) -> ResponseEnvelope:
    return run(
        build_service(scene.world, scene.providers),
        scene,
        Capability.GOODNOTES_PROPOSE,
        Purpose.GOODNOTES_PROPOSAL,
        command,
    )


def _segment() -> dict[str, object]:
    return {
        "kind": "NOTE_UNIT",
        "geometry": {"x_min": 0.1, "y_min": 0.1, "width": 0.2, "height": 0.2},
        "transcription": "synthetic note",
        "primary_class": "MEETING",
    }


def _proposal_for(work: object, *, digest: str | None = None) -> SubmitGoodNotesProposal:
    return SubmitGoodNotesProposal(
        run_id=work.run_id,  # type: ignore[attr-defined]
        page_version_id=work.page_version_id,  # type: ignore[attr-defined]
        content_sha256=digest or work.content_sha256,  # type: ignore[attr-defined]
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        idempotency_key="canary-goodnotes-propose-0001",
        segments=(_segment(),),
    )


def test_mcp_tools_exist_and_are_command_derived() -> None:
    assert WORK_TOOL.name == Capability.GOODNOTES_WORK.value
    assert CONTENT_TOOL.name == Capability.GOODNOTES_CONTENT.value
    assert PROPOSE_TOOL.name == Capability.GOODNOTES_PROPOSE.value
    assert _COMMANDS[Capability.GOODNOTES_WORK] is GetGoodNotesWork
    assert _COMMANDS[Capability.GOODNOTES_CONTENT] is GetGoodNotesContent
    assert _COMMANDS[Capability.GOODNOTES_PROPOSE] is SubmitGoodNotesProposal
    assert GetGoodNotesWork.capability is Capability.GOODNOTES_WORK
    assert GetGoodNotesContent.capability is Capability.GOODNOTES_CONTENT
    assert SubmitGoodNotesProposal.capability is Capability.GOODNOTES_PROPOSE
    assert WORK_TOOL.description
    assert CONTENT_TOOL.description
    assert PROPOSE_TOOL.description
    assert "immutable" in (WORK_TOOL.description or "")
    assert "pinned visual" in (CONTENT_TOOL.description or "")
    assert "Do not write canonical" in (PROPOSE_TOOL.description or "")
    payload_fields = (CONTENT_TOOL.input_schema.get("properties") or {}).get("payload", {}).get(
        "properties"
    ) or {}
    assert "path" not in payload_fields
    assert "principal_id" not in payload_fields
    assert {"run_id", "page_version_id", "content_sha256"} <= set(payload_fields)


def test_task_profile_allowlist_is_work_content_and_propose() -> None:
    names = profile_tool_names()
    assert names == frozenset(
        {
            Capability.GOODNOTES_WORK.value,
            Capability.GOODNOTES_CONTENT.value,
            Capability.GOODNOTES_PROPOSE.value,
        }
    )
    assert (
        frozenset(
            {
                Capability.GOODNOTES_WORK,
                Capability.GOODNOTES_CONTENT,
                Capability.GOODNOTES_PROPOSE,
            }
        )
        == ALLOWED_CAPABILITIES
    )
    assert names.isdisjoint(FORBIDDEN_SUBSTITUTES)
    assert Capability.KNOWLEDGE_SEARCH.value not in names
    assert not any("deliver" in name or "reconcil" in name or "correct" in name for name in names)
    assert not any("summary" in name for name in names)


def test_draft_artifact_matches_the_repository_profile() -> None:
    document = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert document["status"] == DRAFT_STATUS
    assert document["task_name"] == TASK_NAME
    assert document["mcp_surface"] == "my-pa"
    assert frozenset(document["allowed_capabilities"]) == profile_tool_names()
    assert document["constraints"]["no_direct_db_writes"] is True
    assert document["constraints"]["must_not_emit_canonical_new_only_summary"] is True
    assert Capability.KNOWLEDGE_SEARCH.value in document["not_in_allowlist"]


def test_gate_defaults_off_and_does_not_touch_ocr_composition() -> None:
    settings = _settings()
    assert settings.goodnotes_durable_note_intelligence_enabled is False
    assert durable_note_task_is_activated(settings) is False
    assert activated_task_capabilities(settings) == frozenset()
    loaded = load_settings({f"{ENV_PREFIX}DATABASE_URL": DSN})
    assert loaded.goodnotes_durable_note_intelligence_enabled is False
    enabled = load_settings(
        {
            f"{ENV_PREFIX}DATABASE_URL": DSN,
            f"{ENV_PREFIX}GOODNOTES_DURABLE_NOTE_INTELLIGENCE_ENABLED": "true",
        }
    )
    assert activated_task_capabilities(enabled) == ALLOWED_CAPABILITIES
    source = inspect.getsource(compose_local_goodnotes_runtime)
    assert "durable_note" not in source
    assert "goodnotes_durable_note_intelligence_enabled" not in inspect.getsource(
        goodnotes_bootstrap
    )


def test_work_then_content_then_propose_succeeds_on_synthetic_staged_data(scene: Scene) -> None:
    work = staged_goodnotes_work(scene)
    raster = staged_goodnotes_raster(scene)
    assert raster.page_version_id == work.page_version_id
    assert raster.exact_render_sha256 != work.content_sha256
    handle = succeeded(
        _work(scene, GetGoodNotesWork(run_id=work.run_id, page_version_id=work.page_version_id))
    )
    assert handle["content_sha256"] == work.content_sha256
    assert "transcription" not in handle
    assert "body" not in handle
    png = succeeded(
        _content(
            scene,
            GetGoodNotesContent(
                run_id=handle["run_id"],
                page_version_id=handle["page_version_id"],
                content_sha256=str(handle["content_sha256"]),
            ),
        )
    )
    assert png["media_type"] == "image/png"
    assert png["content_base64"]
    assert "path" not in png
    result = succeeded(_propose(scene, _proposal_for(work, digest=str(handle["content_sha256"]))))
    assert result["replayed"] is False
    assert str(result["proposal_id"]).startswith("gnprp_")
    assert "body" not in result
    assert "transcription" not in result
    assert scene.world.goodnotes_proposals


def test_auth_failure_fail_closes_without_a_proposal_write(scene: Scene) -> None:
    work = staged_goodnotes_work(scene)
    stranger = operator()
    denied = build_service(scene.world, scene.providers).invoke(
        metadata_for(Capability.GOODNOTES_PROPOSE, Purpose.GOODNOTES_PROPOSAL, stranger),
        _proposal_for(work),
        principal=stranger,
    )
    assert denied.error is not None
    assert denied.error.code in {ErrorCode.DENIED, ErrorCode.NOT_FOUND}
    assert not scene.world.goodnotes_proposals
    unauthenticated = Principal(
        principal_id=scene.principal.principal_id,
        kind=PrincipalKind.OPERATOR,
        authenticated=False,
    )
    closed = build_service(scene.world, scene.providers).invoke(
        metadata_for(Capability.GOODNOTES_PROPOSE, Purpose.GOODNOTES_PROPOSAL, unauthenticated),
        _proposal_for(work),
        principal=unauthenticated,
    )
    assert closed.error is not None
    assert closed.error.code is ErrorCode.DENIED
    assert not scene.world.goodnotes_proposals


def test_mcp_and_content_transfer_failure_fail_closes(scene: Scene) -> None:
    work = staged_goodnotes_work(scene)
    assert mcp_profile_refuses(Capability.KNOWLEDGE_SEARCH.value, published=PUBLISHED)
    assert mcp_profile_refuses("goodnotes.deliver", published=PUBLISHED)
    assert not mcp_profile_refuses(Capability.GOODNOTES_WORK.value, published=PUBLISHED)
    assert not mcp_profile_refuses(Capability.GOODNOTES_CONTENT.value, published=PUBLISHED)
    assert not mcp_profile_refuses(Capability.GOODNOTES_PROPOSE.value, published=PUBLISHED)
    assert not scene.world.goodnotes_proposals
    missing = _work(
        scene,
        GetGoodNotesWork(
            run_id=issue_stable_id("gnrun", "missing-canary"),
            page_version_id=issue_stable_id("gnver", "missing-canary"),
        ),
    )
    assert missing.error is not None
    assert missing.error.code is ErrorCode.NOT_FOUND
    assert not scene.world.goodnotes_proposals
    mismatch = _propose(scene, _proposal_for(work, digest="b" * 64))
    assert mismatch.error is not None
    assert mismatch.error.code is ErrorCode.INVALID_REQUEST
    assert not scene.world.goodnotes_proposals


def test_profile_cannot_emit_a_new_only_body(scene: Scene) -> None:
    work = staged_goodnotes_work(scene)
    handle = succeeded(
        _work(scene, GetGoodNotesWork(run_id=work.run_id, page_version_id=work.page_version_id))
    )
    result = succeeded(_propose(scene, _proposal_for(work, digest=str(handle["content_sha256"]))))
    for payload in (handle, result):
        assert "body" not in payload
        assert "summary" not in payload
        assert "new_only" not in payload
    module = inspect.getmodule(activated_task_capabilities)
    assert module is not None
    source = inspect.getsource(module)
    assert "build_new_only_summary" not in source
    assert "goodnotes_delivery" not in source
    assert not any(name.endswith(".deliver") or "summary" in name for name in profile_tool_names())
