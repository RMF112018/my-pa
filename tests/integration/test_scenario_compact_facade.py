"""Schedule Scenarios S6-3 package I10-C: the plane end to end through the compact MCP facade.

Schedule scenarios contract sections 6.7, 9.4, 15.12.2 and 15.12.3 and the
section 15.16.2 crosswalk (the S5b-2 precedent,
`tests/integration/test_schedule_compact_facade.py`): the real remote MCP app
(`create_remote_mcp_app`, driven in process over httpx's ASGI transport) over a
real `ApplicationService` on PostgreSQL with the lineage, Schedule and Schedule
Scenarios planes composed, compact publication on and durable grants on the
named capabilities.

* `my_pa.describe` lists exactly the eligible client-usable plane names
  (feature `schedule`, kinds `write`/`read`), never an operator name or an
  ungranted one;
* `my_pa.write` creates a scenario, appends a version, runs the server CPM,
  records a client-asserted output and proposes a baseline; `my_pa.read` reads
  each back; `records.associations.assert` (`concerns`, version -> Issue) is
  `client_identified`;
* an operator name and an ungranted name are `unsupported` at every wrapper;
* the stamped idempotency key binds the OAuth client: 2 clients' identical
  payloads create 2 rows, one client's identical retry replays;
* a ChatLLM client holding exactly its planner-provisioned `chatllm-data-v13`
  grants reaches the 22 and none of the 4.

Every identity and every body here is synthetic.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any, Final

import httpx2
import pytest

from my_pa.adapters.mcp.chatllm_gateway import (
    DESCRIBE_TOOL,
    OPERATOR_TOOL,
    READ_TOOL,
    WRITE_TOOL,
    facade_kind,
)
from my_pa.adapters.mcp.remote import MCP_PATH, RemoteAccessContext, create_remote_mcp_app
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    composed_capabilities,
    diff_chatllm_data_profile,
    plan_chatllm_grant_actions,
)
from my_pa.application.commands import CreateCapture, CreateIssue
from my_pa.domain.identity.chatllm_capability_policy import SCHEDULE_SCENARIO_DATA_NAMES
from my_pa.domain.identity.operation import Capability, is_operator_only, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.schedule_cpm_lease import dispose_lease_engines
from tests.database.schedule_capability_harness import PRINCIPAL, ScheduleRuntime, World
from tests.database.test_schedule_scenario_capabilities import (
    CALENDARS,
    OPERATOR_WRITES,
    WRITES,
    _key,
    _publish,
    _rename,
)
from tests.database.test_schedule_scenario_lineage import BODY, LineagePlane, _passage, _sha

pytestmark = pytest.mark.database

CLIENT: Final = "synthetic-scenario-facade-client"
OTHER: Final = "synthetic-scenario-facade-other"
_HEADERS: Final = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
#: The 22 client-usable plane names and the 4 operator baseline decisions.
CLIENT_USABLE: Final = frozenset(SCHEDULE_SCENARIO_DATA_NAMES)
OPERATOR: Final = frozenset(OPERATOR_WRITES)
#: One client-usable name left ungranted (the "unadmitted" name).
UNGRANTED: Final = Capability.SCHEDULE_BASELINES_COMPARE
LINEAGE_NAMES: Final = (
    Capability.RECORDS_ASSOCIATIONS_ASSERT,
    Capability.ISSUES_READ,
    Capability.CAPTURE_READ,
)

type Grants = frozenset[tuple[Capability, Purpose | None]]


def _grant(*capabilities: Capability) -> Grants:
    return frozenset(
        (capability, sorted(permitted_purposes(capability))[0]) for capability in capabilities
    )


def _context(grants: Grants, client: str = CLIENT, **options: Any) -> RemoteAccessContext:  # noqa: ANN401
    return RemoteAccessContext(
        Principal(principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True),
        allowed_capabilities=frozenset(capability.value for capability, _ in grants),
        capability_purposes=grants,
        compact_publication=True,
        authenticated_client_id=client,
        **options,
    )


def _app(service: Any, contexts: Mapping[str, RemoteAccessContext]) -> Any:  # noqa: ANN401
    def resolve(authorization: str | None) -> RemoteAccessContext | None:
        if authorization is None or not authorization.startswith("Bearer "):
            return None
        return contexts.get(authorization.removeprefix("Bearer "))

    return create_remote_mcp_app(
        service,
        resolve_access=resolve,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
        resource="http://testserver",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )


def _call(name: str, arguments: object) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


async def _exchange(app: Any, requests: list[tuple[str, object]]) -> list[Any]:  # noqa: ANN401
    answers: list[Any] = []
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        for credential, body in requests:
            response = await client.post(
                MCP_PATH,
                headers={**_HEADERS, "Authorization": f"Bearer {credential}"},
                content=json.dumps(body).encode(),
            )
            assert response.status_code == 200, response.text
            answers.append(response.json())
    return answers


def _run(
    facade: tuple[Any, Mapping[str, RemoteAccessContext]], requests: list[tuple[str, object]]
) -> list[Any]:
    """One exchange on a fresh app (a session manager runs once per app)."""
    service, contexts = facade
    return asyncio.run(_exchange(_app(service, contexts), requests))


def _result(answer: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    result = answer["result"]
    (content,) = result["content"]
    return bool(result.get("isError")), json.loads(content["text"])


def _ok(answer: Mapping[str, Any]) -> dict[str, Any]:
    failed, document = _result(answer)
    assert not failed, document
    return document.get("result", document)


def _refusal(answer: Mapping[str, Any]) -> tuple[str, list[str]]:
    failed, document = _result(answer)
    assert failed, document
    problem = document.get("error", document)
    return str(problem["code"]), list(problem.get("safe_details") or [])


def _invoke(capability: Capability, payload: dict[str, Any]) -> dict[str, object]:
    wrapper = WRITE_TOOL if facade_kind(capability) == "write" else READ_TOOL
    return _call(wrapper, {"capability": capability.value, "arguments": {"payload": payload}})


@pytest.fixture
def rt(disposable_database: str) -> Iterator[ScheduleRuntime]:
    runtime = ScheduleRuntime(disposable_database)
    try:
        yield runtime
    finally:
        runtime.close()
        dispose_lease_engines()


@pytest.fixture
def w(rt: ScheduleRuntime) -> World:
    return rt.world(PRINCIPAL, "s63fac")


def _create_payload(publication: str) -> dict[str, Any]:
    return {
        "from_publication_id": publication,
        "name": "Synthetic facade what-if",
        "label": "what_if",
        "minutes_per_source_unit": 480,
        "calendars": CALENDARS,
        "default_calendar": "std",
    }


def test_scenario_facade_end_to_end(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sections 6.7 and 15.12.3 (P3-32, P3-33): describe, write, read, refuse."""
    plane = LineagePlane(rt)
    publication = _publish(rt, w, monkeypatch)
    issue = plane.ok(CreateIssue(title="Synthetic facade Issue", idempotency_key=_key("issue")))[
        "issue"
    ]["issue_id"]
    captured = plane.ok(CreateCapture(text=BODY, idempotency_key=_key("capture")))
    anchor = {
        "family": "capture_version",
        "root_id": captured["capture_id"],
        "version_kind": "immutable_version",
        "version_id": captured["version_id"],
        "source_sha256": _sha(BODY),
        "role": "corroborates",
        **_passage("the crane slips a week"),
    }
    granted = (CLIENT_USABLE - {UNGRANTED}) | OPERATOR
    app = (plane.service, {"client": _context(_grant(*granted, *LINEAGE_NAMES))})
    eligible = CLIENT_USABLE - {UNGRANTED}
    listed, *refused = _run(
        app,
        [
            ("client", _call(DESCRIBE_TOOL, {"feature": "schedule", "limit": 100})),
            *[
                ("client", _call(DESCRIBE_TOOL, {"capability": capability.value}))
                for capability in sorted(OPERATOR | {UNGRANTED})
            ],
            *[
                (
                    "client",
                    _call(
                        wrapper,
                        {"capability": capability.value, "arguments": {"payload": {}}},
                    ),
                )
                for capability in sorted(OPERATOR | {UNGRANTED})
                for wrapper in (READ_TOOL, WRITE_TOOL, OPERATOR_TOOL)
            ],
        ],
    )
    _failed, catalog = _result(listed)
    items = {item["capability"]: item for item in catalog["items"]}
    # Exactly the eligible client-usable names, each `schedule`, its kind, its summary.
    assert set(items) == {capability.value for capability in eligible}
    summaries = {tool.name: tool.description for tool in TOOLS}
    for name, item in items.items():
        capability = Capability(name)
        assert item["feature"] == "schedule", name
        assert item["kind"] == facade_kind(capability), name
        assert item["kind"] == ("write" if capability in WRITES else "read"), name
        assert item["summary"] == summaries[name], name
        assert item["idempotent"] is (capability in WRITES), name
        assert not is_operator_only(capability)
    for answer in refused:
        assert _refusal(answer) == ("unsupported", [])
    # Writes: create, append, run the CPM, record an output, propose.
    (created,) = (
        _ok(answer)
        for answer in _run(
            app,
            [
                (
                    "client",
                    _invoke(Capability.SCHEDULE_SCENARIOS_CREATE, _create_payload(publication)),
                )
            ],
        )
    )
    assert created["replayed"] is False and created["version_no"] == 1
    appended, run = (
        _ok(answer)
        for answer in _run(
            app,
            [
                (
                    "client",
                    _invoke(
                        Capability.SCHEDULE_SCENARIO_VERSIONS_CREATE,
                        {
                            "scenario_id": created["scenario_id"],
                            "expected_head_version_no": 1,
                            "label": "update",
                            "change_set": [_rename()],
                        },
                    ),
                ),
                (
                    "client",
                    _invoke(
                        Capability.SCHEDULE_CPM_RUNS_CREATE, {"version_id": created["version_id"]}
                    ),
                ),
            ],
        )
    )
    assert appended["version_no"] == 2
    (version,) = (
        _ok(answer)
        for answer in _run(
            app,
            [
                (
                    "client",
                    _invoke(
                        Capability.SCHEDULE_SCENARIO_VERSIONS_READ,
                        {"version_id": created["version_id"]},
                    ),
                )
            ],
        )
    )
    document = {
        "version_id": version["version_id"],
        "content_sha256": version["content_sha256"],
        "kind": "monte_carlo",
        "run_config": {
            "tool_name": "synthetic-mc",
            "tool_version": "1.0",
            "seed": "seed-0001",
            "iterations": 1000,
            "sampling": "independent",
            "engine": "other",
            "distribution_spec_sha256": version["distribution_spec_sha256"],
        },
        "finish_percentiles": [{"p": 50, "finish": "2026-06-01T17:00"}],
    }
    output, proposal, association = (
        _ok(answer)
        for answer in _run(
            app,
            [
                (
                    "client",
                    _invoke(Capability.SCHEDULE_SCENARIO_OUTPUTS_RECORD, {"document": document}),
                ),
                (
                    "client",
                    _invoke(
                        Capability.SCHEDULE_BASELINES_PROPOSE,
                        {"publication_id": publication, "type": "contract", "reason": "Synthetic"},
                    ),
                ),
                (
                    "client",
                    _invoke(
                        Capability.RECORDS_ASSOCIATIONS_ASSERT,
                        {
                            "from_record": {
                                "family": "scenario_version",
                                "record_id": appended["version_id"],
                            },
                            "to_record": {"family": "situation", "record_id": issue},
                            "relation_type": "concerns",
                            "evidence_anchors": [anchor],
                        },
                    ),
                ),
            ],
        )
    )
    assert output["labels"]["authority"] == "client_asserted"
    assert proposal["status"] == "proposed" and proposal["labels"]["authoritative"] is False
    assert association["association"]["acceptance_basis"] == "client_identified"
    assert association["association"]["relation_type"] == "concerns"
    # Reads: each written record back.
    reads = {
        Capability.SCHEDULE_SCENARIOS_READ: {"scenario_id": created["scenario_id"]},
        Capability.SCHEDULE_SCENARIO_VERSIONS_READ: {"version_id": appended["version_id"]},
        Capability.SCHEDULE_CPM_RUNS_READ: {"cpm_run_id": run["cpm_run_id"]},
        Capability.SCHEDULE_SCENARIO_OUTPUTS_READ: {"output_id": output["output_id"]},
        Capability.SCHEDULE_BASELINES_READ: {"baseline_id": proposal["baseline_id"]},
        Capability.SCHEDULE_SCENARIOS_LIST: {"project_id": w.project},
    }
    answers = _run(
        app, [("client", _invoke(capability, payload)) for capability, payload in reads.items()]
    )
    served = dict(zip(reads, (_ok(answer) for answer in answers), strict=True))
    assert served[Capability.SCHEDULE_SCENARIOS_READ]["scenario_id"] == created["scenario_id"]
    assert served[Capability.SCHEDULE_SCENARIO_VERSIONS_READ]["version_no"] == 2
    assert served[Capability.SCHEDULE_CPM_RUNS_READ]["cpm_run_id"] == run["cpm_run_id"]
    assert served[Capability.SCHEDULE_SCENARIO_OUTPUTS_READ]["output_id"] == output["output_id"]
    assert served[Capability.SCHEDULE_BASELINES_READ]["status"] == "proposed"
    assert [s["scenario_id"] for s in served[Capability.SCHEDULE_SCENARIOS_LIST]["scenarios"]] == [
        created["scenario_id"]
    ]


def test_identical_payloads_from_two_clients_create_two_rows(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R8-F09 through the facade: the stamped key binds the OAuth client."""
    plane = LineagePlane(rt)
    publication = _publish(rt, w, monkeypatch)
    grants = _grant(*CLIENT_USABLE)
    app = (
        plane.service,
        {"one": _context(grants, CLIENT), "two": _context(grants, OTHER)},
    )
    payload = _create_payload(publication)
    first, second = (
        _ok(answer)
        for answer in _run(
            app,
            [
                ("one", _invoke(Capability.SCHEDULE_SCENARIOS_CREATE, payload)),
                ("two", _invoke(Capability.SCHEDULE_SCENARIOS_CREATE, payload)),
            ],
        )
    )
    assert first["scenario_id"] != second["scenario_id"]
    assert (first["replayed"], second["replayed"]) == (False, False)
    assert rt.scalar("SELECT count(*) FROM knowledge.schedule_scenarios") == 2


def test_identical_retry_from_one_client_replays(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S6-3-D06 through the facade: one client's identical retry replays the stored row."""
    plane = LineagePlane(rt)
    publication = _publish(rt, w, monkeypatch)
    app = (plane.service, {"one": _context(_grant(*CLIENT_USABLE), CLIENT)})
    payload = _create_payload(publication)
    first, again = (
        _ok(answer)
        for answer in _run(
            app,
            [
                ("one", _invoke(Capability.SCHEDULE_SCENARIOS_CREATE, payload)),
                ("one", _invoke(Capability.SCHEDULE_SCENARIOS_CREATE, payload)),
            ],
        )
    )
    assert again["replayed"] is True and again["scenario_id"] == first["scenario_id"]
    assert rt.scalar("SELECT count(*) FROM knowledge.schedule_scenarios") == 1


def test_a_chatllm_client_with_v13_grants_reaches_the_22(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 15.12.1: the v13 planner's grants reach the 22 and never the 4."""
    plane = LineagePlane(rt)
    publication = _publish(rt, w, monkeypatch)
    implemented = frozenset(Capability)
    planes = ChatLLMCompositionPlanes(
        managed_documents=False,
        relationship_intelligence=False,
        relationship_intelligence_writes=False,
        relationship_memory=False,
        constraints=False,
        schedule=True,
        schedule_scenarios=True,
    )
    composed = composed_capabilities(implemented, planes)
    now = datetime(2026, 11, 11, 12, tzinfo=UTC)
    diff = diff_chatllm_data_profile(
        implemented=implemented,
        composed=composed,
        grants=(),
        now=now,
        resource="http://testserver",
        scope="my-pa.read",
    )
    actions = plan_chatllm_grant_actions(
        diff, (), now=now, resource="http://testserver", scope="my-pa.read"
    )
    provisioned: Grants = frozenset(
        (action.capability, action.purpose) for action in actions if action.kind == "add"
    )
    names = {capability for capability, _ in provisioned}
    assert names >= CLIENT_USABLE
    assert not names & OPERATOR
    app = (plane.service, {"chatllm": _context(provisioned, "synthetic-chatllm-client")})
    listed, created, refused = _run(
        app,
        [
            ("chatllm", _call(DESCRIBE_TOOL, {"feature": "schedule", "limit": 100})),
            (
                "chatllm",
                _invoke(Capability.SCHEDULE_SCENARIOS_CREATE, _create_payload(publication)),
            ),
            (
                "chatllm",
                _call(
                    OPERATOR_TOOL,
                    {
                        "capability": Capability.SCHEDULE_BASELINES_APPROVE.value,
                        "arguments": {"payload": {}},
                    },
                ),
            ),
        ],
    )
    _failed, catalog = _result(listed)
    seen = {item["capability"] for item in catalog["items"]}
    assert {capability.value for capability in CLIENT_USABLE} <= seen
    assert not seen & {capability.value for capability in OPERATOR}
    assert _ok(created)["replayed"] is False
    assert _refusal(refused) == ("unsupported", [])
