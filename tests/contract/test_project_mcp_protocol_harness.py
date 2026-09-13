"""GAP-009: synthetic Project management workflow over the MCP protocol.

Proves the protocol → ApplicationService → in-memory persistence chain on
synthetic data. Follows the Task protocol harness and Constraint authoring
admission: a real JSON-RPC exchange through `mcp_transport`, no live database,
and no operator runtime attestation (GAP-008 remains OPEN).

The in-memory FakeUnitOfWork keeps continuity-authored Tasks off the
task-management store. After `continuity.tasks.create`, the harness applies the
same `_mirror_continuity_task` fixture WP-MCP-PROJ-05 uses so `tasks.update`
and `tasks.list` can continue over MCP.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from tests.conftest import WHEN, Scene, build_service, operator
from tests.contract.test_transport_parity import document
from tests.transports import Answer, mcp_transport

from my_pa.adapters.normalization import PAYLOAD_KEY
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.situation.continuity import ContinuityAcceptanceKind, ContinuityEvidenceState
from my_pa.domain.task.lifecycle import TaskLifecycleState, TaskOriginKind
from my_pa.domain.task.task import Task as TaskV2

PROJECT: Final[tuple[Capability, ...]] = (
    Capability.CONTINUITY_PROJECTS,
    Capability.CONTINUITY_PROJECTS_READ,
    Capability.CONTINUITY_PROJECTS_CREATE,
    Capability.CONTINUITY_PROJECTS_UPDATE,
    Capability.CONTINUITY_PROJECTS_CLOSE,
)

ROLE_OF_RECORD: Final = "ARCHITECT_OF_RECORD"


def _doc(
    principal: Principal,
    capability: Capability,
    payload: Mapping[str, Any],
    *,
    request_id: str,
) -> dict[str, Any]:
    body = document(capability, principal.principal_id, payload)
    return {**body, "request_id": request_id}


def _error_code(answer: Answer) -> str:
    error = answer.document.get("error") or answer.document
    return str(error["code"])


def _result(answer: Answer, *, where: str) -> dict[str, Any]:
    assert not answer.failed, f"{where} failed: {answer.document}"
    result = answer.document["result"]
    assert isinstance(result, dict)
    return result


def _mirror_continuity_task(scene: Scene, principal: Principal, payload: Mapping[str, Any]) -> None:
    """Copy a continuity-authored Task into the in-memory task-management store."""
    task_id = str(payload["task_id"])
    if any(row.task_id == task_id for row in scene.world.tasks_v2):
        return
    scene.world.tasks_v2.append(
        TaskV2(
            task_id=task_id,
            principal_id=principal.principal_id,
            title=str(payload["title"]),
            lifecycle_state=TaskLifecycleState.OPEN,
            evidence_state=ContinuityEvidenceState.ACCEPTED,
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
            project_id=None if payload["project_id"] is None else str(payload["project_id"]),
            acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL,
        )
    )


def test_tools_list_and_describe_publish_project_capabilities(scene: Scene) -> None:
    """1. tools/list publishes the five Project tools with descriptions and schemas."""
    served = mcp_transport(build_service(scene.world, scene.providers), scene.principal)
    with served as session:
        listed = session.list_tools()
    published = {tool.name: tool for tool in listed.tools}
    for capability in PROJECT:
        assert capability.value in published, f"{capability.value} missing from tools/list"
        tool = published[capability.value]
        assert tool.description, f"{capability.value} has no description"
        assert "payload" in tool.description
        schema = tool.input_schema
        assert PAYLOAD_KEY in schema["properties"]
        payload = schema["properties"][PAYLOAD_KEY]
        assert payload["type"] == "object"
        assert payload["additionalProperties"] is False
        if capability in (
            Capability.CONTINUITY_PROJECTS_UPDATE,
            Capability.CONTINUITY_PROJECTS_CLOSE,
        ):
            assert "expected_version" in payload["required"]
            assert "expected_version" in tool.description


def test_project_management_workflow_over_mcp(scene: Scene) -> None:
    """Walk create → read → list → update → close → participation → task over MCP.

    Covers scenarios 2-8 in one sequential exchange because later steps need
    identifiers and versions returned by earlier ones.
    """
    service = build_service(scene.world, scene.providers)
    principal = scene.principal
    served = mcp_transport(service, principal)

    with served as session:
        # -- 2. create Project (active, prj_, version 1, replay-safe) --
        create_answer = session.send(
            Capability.CONTINUITY_PROJECTS_CREATE.value,
            _doc(
                principal,
                Capability.CONTINUITY_PROJECTS_CREATE,
                {
                    "name": "Alpha Harbour",
                    "description": "First synthetic harbour",
                    "idempotency_key": "proj-07-create-alpha-0001",
                },
                request_id="req-proj-07-create-alpha",
            ),
        )
        created = _result(create_answer, where="continuity.projects.create")
        project_id = created["project_id"]
        assert project_id.startswith("prj_")
        assert created["state"] == "active"
        assert created["version"] == 1
        assert created["name"] == "Alpha Harbour"
        assert created["replayed"] is False

        replay_answer = session.send(
            Capability.CONTINUITY_PROJECTS_CREATE.value,
            _doc(
                principal,
                Capability.CONTINUITY_PROJECTS_CREATE,
                {
                    "name": "Alpha Harbour",
                    "description": "First synthetic harbour",
                    "idempotency_key": "proj-07-create-alpha-0001",
                },
                request_id="req-proj-07-create-alpha-replay",
            ),
        )
        replayed = _result(replay_answer, where="continuity.projects.create replay")
        assert replayed["project_id"] == project_id
        assert replayed["version"] == 1
        assert replayed["replayed"] is True

        # -- 3. read by exact ID --
        read_answer = session.send(
            Capability.CONTINUITY_PROJECTS_READ.value,
            _doc(
                principal,
                Capability.CONTINUITY_PROJECTS_READ,
                {"project_id": project_id},
                request_id="req-proj-07-read-alpha",
            ),
        )
        read = _result(read_answer, where="continuity.projects.read")
        assert read["project_id"] == project_id
        assert read["name"] == "Alpha Harbour"
        assert read["state"] == "active"
        assert read["version"] == 1
        assert read["closed_at"] is None

        beta_created = _result(
            session.send(
                Capability.CONTINUITY_PROJECTS_CREATE.value,
                _doc(
                    principal,
                    Capability.CONTINUITY_PROJECTS_CREATE,
                    {"name": "Beta Quay", "idempotency_key": "proj-07-create-beta-0001"},
                    request_id="req-proj-07-create-beta",
                ),
            ),
            where="continuity.projects.create beta",
        )
        beta_id = beta_created["project_id"]
        closed_seed = _result(
            session.send(
                Capability.CONTINUITY_PROJECTS_CREATE.value,
                _doc(
                    principal,
                    Capability.CONTINUITY_PROJECTS_CREATE,
                    {"name": "Closed Alpha", "idempotency_key": "proj-07-create-closed-0001"},
                    request_id="req-proj-07-create-closed",
                ),
            ),
            where="continuity.projects.create closed seed",
        )

        # -- 4. list with state/query/exact_name and cursor (two pages, no dup/skip) --
        by_state = _result(
            session.send(
                Capability.CONTINUITY_PROJECTS.value,
                _doc(
                    principal,
                    Capability.CONTINUITY_PROJECTS,
                    {"state": "active"},
                    request_id="req-proj-07-list-state",
                ),
            ),
            where="continuity.projects list state",
        )
        active_names = {row["name"] for row in by_state["projects"]}
        assert {"Alpha Harbour", "Beta Quay", "Closed Alpha"} <= active_names

        by_query = _result(
            session.send(
                Capability.CONTINUITY_PROJECTS.value,
                _doc(
                    principal,
                    Capability.CONTINUITY_PROJECTS,
                    {"query": "Alpha"},
                    request_id="req-proj-07-list-query",
                ),
            ),
            where="continuity.projects list query",
        )
        assert {row["name"] for row in by_query["projects"]} == {"Alpha Harbour", "Closed Alpha"}

        by_name = _result(
            session.send(
                Capability.CONTINUITY_PROJECTS.value,
                _doc(
                    principal,
                    Capability.CONTINUITY_PROJECTS,
                    {"exact_name": "Alpha Harbour"},
                    request_id="req-proj-07-list-exact-name",
                ),
            ),
            where="continuity.projects list exact_name",
        )
        assert [row["project_id"] for row in by_name["projects"]] == [project_id]

        first_page = session.send(
            Capability.CONTINUITY_PROJECTS.value,
            _doc(
                principal,
                Capability.CONTINUITY_PROJECTS,
                {"page_size": 1},
                request_id="req-proj-07-list-page-1",
            ),
        )
        first = _result(first_page, where="continuity.projects list page 1")
        first_ids = [row["project_id"] for row in first["projects"]]
        truncation = first_page.document["disclosure"]["truncation"]
        assert truncation["is_truncated"] is True
        cursor = truncation["next_cursor"]
        assert cursor == first_ids[0]
        second_page = session.send(
            Capability.CONTINUITY_PROJECTS.value,
            _doc(
                principal,
                Capability.CONTINUITY_PROJECTS,
                {"page_size": 1, "after": cursor},
                request_id="req-proj-07-list-page-2",
            ),
        )
        second = _result(second_page, where="continuity.projects list page 2")
        second_ids = [row["project_id"] for row in second["projects"]]
        owned_ids = {project_id, beta_id, closed_seed["project_id"]}
        assert len(first_ids) == 1
        assert len(second_ids) == 1
        assert set(first_ids).isdisjoint(second_ids)
        assert set(first_ids + second_ids) <= owned_ids

        # -- 5. update name/description and active↔on_hold; version increments --
        renamed = _result(
            session.send(
                Capability.CONTINUITY_PROJECTS_UPDATE.value,
                _doc(
                    principal,
                    Capability.CONTINUITY_PROJECTS_UPDATE,
                    {
                        "project_id": project_id,
                        "expected_version": 1,
                        "idempotency_key": "proj-07-rename-0001",
                        "name": "Alpha Harbour Revised",
                        "description": "Held description",
                    },
                    request_id="req-proj-07-rename",
                ),
            ),
            where="continuity.projects.update name",
        )
        assert renamed["name"] == "Alpha Harbour Revised"
        assert renamed["description"] == "Held description"
        assert renamed["version"] == 2
        held = _result(
            session.send(
                Capability.CONTINUITY_PROJECTS_UPDATE.value,
                _doc(
                    principal,
                    Capability.CONTINUITY_PROJECTS_UPDATE,
                    {
                        "project_id": project_id,
                        "expected_version": 2,
                        "idempotency_key": "proj-07-hold-0001",
                        "state": "on_hold",
                    },
                    request_id="req-proj-07-hold",
                ),
            ),
            where="continuity.projects.update on_hold",
        )
        assert held["state"] == "on_hold"
        assert held["version"] == 3
        resumed = _result(
            session.send(
                Capability.CONTINUITY_PROJECTS_UPDATE.value,
                _doc(
                    principal,
                    Capability.CONTINUITY_PROJECTS_UPDATE,
                    {
                        "project_id": project_id,
                        "expected_version": 3,
                        "idempotency_key": "proj-07-resume-0001",
                        "state": "active",
                    },
                    request_id="req-proj-07-resume",
                ),
            ),
            where="continuity.projects.update active",
        )
        assert resumed["state"] == "active"
        assert resumed["version"] == 4

        owned = session.send(
            Capability.CONTINUITY_PROJECTS_UPDATE.value,
            _doc(
                principal,
                Capability.CONTINUITY_PROJECTS_UPDATE,
                {
                    "project_id": project_id,
                    "expected_version": 4,
                    "idempotency_key": "proj-07-system-owned-0001",
                    "name": "Should not land",
                    "version": 99,
                },
                request_id="req-proj-07-system-owned",
            ),
        )
        assert owned.failed, "system-owned payload fields must be refused"
        assert _error_code(owned) == ErrorCode.INVALID_REQUEST.value

        # -- 6. close; closed_at server-owned; reopen rejected --
        closed = _result(
            session.send(
                Capability.CONTINUITY_PROJECTS_CLOSE.value,
                _doc(
                    principal,
                    Capability.CONTINUITY_PROJECTS_CLOSE,
                    {
                        "project_id": project_id,
                        "expected_version": 4,
                        "idempotency_key": "proj-07-close-0001",
                    },
                    request_id="req-proj-07-close",
                ),
            ),
            where="continuity.projects.close",
        )
        assert closed["state"] == "closed"
        assert closed["version"] == 5
        closed_read = _result(
            session.send(
                Capability.CONTINUITY_PROJECTS_READ.value,
                _doc(
                    principal,
                    Capability.CONTINUITY_PROJECTS_READ,
                    {"project_id": project_id},
                    request_id="req-proj-07-read-closed",
                ),
            ),
            where="continuity.projects.read after close",
        )
        assert closed_read["closed_at"] is not None
        reopen = session.send(
            Capability.CONTINUITY_PROJECTS_UPDATE.value,
            _doc(
                principal,
                Capability.CONTINUITY_PROJECTS_UPDATE,
                {
                    "project_id": project_id,
                    "expected_version": 5,
                    "idempotency_key": "proj-07-reopen-0001",
                    "state": "active",
                },
                request_id="req-proj-07-reopen",
            ),
        )
        assert reopen.failed, "a closed Project must not reopen"
        assert _error_code(reopen) == ErrorCode.CONFLICT.value

        # -- 7. participation create/list via project_id --
        person = _result(
            session.send(
                Capability.ENTITIES_CREATE.value,
                _doc(
                    principal,
                    Capability.ENTITIES_CREATE,
                    {
                        "entity_type": "person",
                        "display_name": "Pat Synthetic",
                        "reason": "A synthetic participant.",
                        "idempotency_key": "proj-07-person-0001",
                    },
                    request_id="req-proj-07-person",
                ),
            ),
            where="entities.create",
        )
        person_id = person["entity_id"]
        assert person_id.startswith("ent_")
        participation = _result(
            session.send(
                Capability.ENTITIES_PARTICIPATIONS_CREATE.value,
                _doc(
                    principal,
                    Capability.ENTITIES_PARTICIPATIONS_CREATE,
                    {
                        "participant_entity_id": person_id,
                        "project_id": beta_id,
                        "project_display_name": "Pat on Beta Quay",
                        "role_basis_code": "contractual",
                        "stakeholder_side_code": "design",
                        "stakeholder_class_code": "core",
                        "relationship_status_code": "active",
                        "role_code": ROLE_OF_RECORD,
                        "idempotency_key": "proj-07-participation-0001",
                    },
                    request_id="req-proj-07-participation",
                ),
            ),
            where="entities.participations.create",
        )
        assert participation["replayed"] is False
        listed_parts = _result(
            session.send(
                Capability.ENTITIES_PARTICIPATIONS_LIST.value,
                _doc(
                    principal,
                    Capability.ENTITIES_PARTICIPATIONS_LIST,
                    {"project_id": beta_id},
                    request_id="req-proj-07-participations-list",
                ),
            ),
            where="entities.participations.list",
        )
        assert listed_parts["perspective"] == "project"
        rows = listed_parts["participations"]
        assert len(rows) == 1
        assert rows[0]["participant_entity_id"] == person_id
        assert rows[0]["role_code"] == ROLE_OF_RECORD

        # -- 8. Task: continuity.tasks.create attached; update reassign/clear; list --
        quay = _result(
            session.send(
                Capability.CONTINUITY_PROJECTS_CREATE.value,
                _doc(
                    principal,
                    Capability.CONTINUITY_PROJECTS_CREATE,
                    {"name": "Quay Wall", "idempotency_key": "proj-07-create-quay-0001"},
                    request_id="req-proj-07-create-quay",
                ),
            ),
            where="continuity.projects.create quay",
        )
        quay_id = quay["project_id"]
        task_created = _result(
            session.send(
                Capability.CONTINUITY_TASKS_CREATE.value,
                _doc(
                    principal,
                    Capability.CONTINUITY_TASKS_CREATE,
                    {
                        "title": "Check the pour",
                        "project_id": beta_id,
                        "idempotency_key": "proj-07-task-0001",
                    },
                    request_id="req-proj-07-task-create",
                ),
            ),
            where="continuity.tasks.create",
        )
        assert task_created["project_id"] == beta_id
        assert task_created["replayed"] is False
        _mirror_continuity_task(scene, principal, task_created)
        task_id = task_created["task_id"]
        reassigned = _result(
            session.send(
                Capability.TASKS_UPDATE.value,
                _doc(
                    principal,
                    Capability.TASKS_UPDATE,
                    {
                        "task_id": task_id,
                        "expected_version": 1,
                        "idempotency_key": "proj-07-task-reassign-0001",
                        "project_id": quay_id,
                    },
                    request_id="req-proj-07-task-reassign",
                ),
            ),
            where="tasks.update reassign",
        )
        assert reassigned["task"]["project_id"] == quay_id
        assert reassigned["task"]["version"] == 2
        scoped = _result(
            session.send(
                Capability.TASKS_LIST.value,
                _doc(
                    principal,
                    Capability.TASKS_LIST,
                    {"project_id": quay_id},
                    request_id="req-proj-07-tasks-list-quay",
                ),
            ),
            where="tasks.list project_id",
        )
        assert [row["task_id"] for row in scoped["tasks"]] == [task_id]
        cleared = _result(
            session.send(
                Capability.TASKS_UPDATE.value,
                _doc(
                    principal,
                    Capability.TASKS_UPDATE,
                    {
                        "task_id": task_id,
                        "expected_version": 2,
                        "idempotency_key": "proj-07-task-clear-0001",
                        "clear_project": True,
                    },
                    request_id="req-proj-07-task-clear",
                ),
            ),
            where="tasks.update clear_project",
        )
        assert cleared["task"]["project_id"] is None
        after_clear = _result(
            session.send(
                Capability.TASKS_LIST.value,
                _doc(
                    principal,
                    Capability.TASKS_LIST,
                    {"project_id": quay_id},
                    request_id="req-proj-07-tasks-list-cleared",
                ),
            ),
            where="tasks.list after clear",
        )
        assert after_clear["tasks"] == []


def test_stale_expected_version_conflicts_over_mcp(scene: Scene) -> None:
    """9. A stale expected_version on continuity.projects.update is conflict."""
    service = build_service(scene.world, scene.providers)
    principal = scene.principal
    served = mcp_transport(service, principal)
    with served as session:
        created = _result(
            session.send(
                Capability.CONTINUITY_PROJECTS_CREATE.value,
                _doc(
                    principal,
                    Capability.CONTINUITY_PROJECTS_CREATE,
                    {"name": "Stale Harbour", "idempotency_key": "proj-07-stale-create-0001"},
                    request_id="req-proj-07-stale-create",
                ),
            ),
            where="continuity.projects.create stale",
        )
        project_id = created["project_id"]
        _result(
            session.send(
                Capability.CONTINUITY_PROJECTS_UPDATE.value,
                _doc(
                    principal,
                    Capability.CONTINUITY_PROJECTS_UPDATE,
                    {
                        "project_id": project_id,
                        "expected_version": 1,
                        "idempotency_key": "proj-07-stale-first-0001",
                        "name": "Stale Harbour, first",
                    },
                    request_id="req-proj-07-stale-first",
                ),
            ),
            where="continuity.projects.update first",
        )
        stale = session.send(
            Capability.CONTINUITY_PROJECTS_UPDATE.value,
            _doc(
                principal,
                Capability.CONTINUITY_PROJECTS_UPDATE,
                {
                    "project_id": project_id,
                    "expected_version": 1,
                    "idempotency_key": "proj-07-stale-second-0001",
                    "name": "Stale Harbour, second",
                },
                request_id="req-proj-07-stale-second",
            ),
        )
    assert stale.failed, "stale expected_version must fail"
    assert _error_code(stale) == ErrorCode.CONFLICT.value


def test_second_principal_cannot_read_or_mutate_over_mcp(scene: Scene) -> None:
    """10. A second Principal cannot read or mutate another Principal's Project."""
    service = build_service(scene.world, scene.providers)
    owner = scene.principal
    stranger = operator()
    with mcp_transport(service, owner) as session:
        created = _result(
            session.send(
                Capability.CONTINUITY_PROJECTS_CREATE.value,
                _doc(
                    owner,
                    Capability.CONTINUITY_PROJECTS_CREATE,
                    {"name": "Owner Harbour", "idempotency_key": "proj-07-owner-create-0001"},
                    request_id="req-proj-07-owner-create",
                ),
            ),
            where="continuity.projects.create owner",
        )
        project_id = created["project_id"]
    with mcp_transport(service, stranger) as session:
        missing = session.send(
            Capability.CONTINUITY_PROJECTS_READ.value,
            _doc(
                stranger,
                Capability.CONTINUITY_PROJECTS_READ,
                {"project_id": project_id},
                request_id="req-proj-07-stranger-read",
            ),
        )
        updated = session.send(
            Capability.CONTINUITY_PROJECTS_UPDATE.value,
            _doc(
                stranger,
                Capability.CONTINUITY_PROJECTS_UPDATE,
                {
                    "project_id": project_id,
                    "expected_version": 1,
                    "idempotency_key": "proj-07-stranger-update-0001",
                    "name": "Should not land",
                },
                request_id="req-proj-07-stranger-update",
            ),
        )
        closed = session.send(
            Capability.CONTINUITY_PROJECTS_CLOSE.value,
            _doc(
                stranger,
                Capability.CONTINUITY_PROJECTS_CLOSE,
                {
                    "project_id": project_id,
                    "expected_version": 1,
                    "idempotency_key": "proj-07-stranger-close-0001",
                },
                request_id="req-proj-07-stranger-close",
            ),
        )
    assert missing.failed and updated.failed and closed.failed
    assert _error_code(missing) == ErrorCode.NOT_FOUND.value
    assert _error_code(updated) == ErrorCode.NOT_FOUND.value
    assert _error_code(closed) == ErrorCode.NOT_FOUND.value
    assert project_id not in str(missing.document.get("error") or missing.document)
