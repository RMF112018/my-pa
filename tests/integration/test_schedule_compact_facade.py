"""CPM Workbench S5b-2: the Schedule reads end to end through the compact MCP facade (database).

Worker and capabilities contract sections 3.13.2-3.13.4 and 6.2 (section 31.5
facade row), the S3.1 Part D precedent
(`tests/integration/test_lineage_s31_compact_facade.py`): the real remote MCP
app (`create_remote_mcp_app`, driven in process over httpx's ASGI transport)
over a real `ApplicationService` on PostgreSQL with the Schedule switch on,
compact publication on and durable grants on the named capabilities.

* `my_pa.describe` lists exactly the eligible Schedule reads (feature
  `schedule`, kind `read`, the catalog summary), never the import;
* `my_pa.read` invokes each read with the canonical strict schema, and the
  wrong wrapper and an unknown field are `invalid_request`;
* the import is absent from every publication -- default, `remote.operator`
  and compact operator -- and `unsupported` at every wrapper, granted or not;
* with the switch off every Schedule name is hidden and `unsupported`;
* a restricted MCP database profile service composes no Schedule capability;
* `capabilities.get`, the committed web fixture and the catalog agree;
* a ChatLLM client holding exactly its planner-provisioned `chatllm-data-v11`
  grants reaches the 6 reads and not the import.

Every identity and every body here is synthetic.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
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
from my_pa.application.commands import GetCapabilities, ListScheduleActivities
from my_pa.bootstrap.gateway import build_gateway_runtime
from my_pa.bootstrap.settings import Settings
from my_pa.domain.identity.operation import Capability, is_operator_only, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from tests.database.schedule_capability_harness import (
    PRINCIPAL,
    Activity,
    ScheduleRuntime,
    World,
    cpm_snapshot,
)

pytestmark = pytest.mark.database

_ROOT: Final = Path(__file__).resolve().parents[2]
_WEB: Final = _ROOT / "web" / "src"
CLIENT: Final = "synthetic-schedule-facade-client"
_HEADERS: Final = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
IMPORT: Final = Capability.SCHEDULE_PUBLICATIONS_IMPORT
READS: Final = (
    Capability.SCHEDULE_SERIES_LIST,
    Capability.SCHEDULE_PUBLICATIONS_LIST,
    Capability.SCHEDULE_PUBLICATIONS_READ,
    Capability.SCHEDULE_ACTIVITIES_LIST,
    Capability.SCHEDULE_ACTIVITIES_HISTORY,
    Capability.SCHEDULE_CHANGES_LIST,
)
SEVEN: Final = frozenset({IMPORT, *READS})
_SEVEN_NAMES: Final = frozenset(capability.value for capability in SEVEN)

type Grants = frozenset[tuple[Capability, Purpose | None]]


def _grant(*capabilities: Capability) -> Grants:
    return frozenset(
        (capability, sorted(permitted_purposes(capability))[0]) for capability in capabilities
    )


def _principal() -> Principal:
    return Principal(principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True)


def _context(grants: Grants, client: str = CLIENT, **options: Any) -> RemoteAccessContext:  # noqa: ANN401
    return RemoteAccessContext(
        _principal(),
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


def _call(name: str, arguments: object, request_id: int = 1) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def _list_tools() -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": 9, "method": "tools/list"}


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


def _run(app: Any, requests: list[tuple[str, object]]) -> list[Any]:  # noqa: ANN401
    return asyncio.run(_exchange(app, requests))


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


def _read(capability: Capability, payload: dict[str, Any]) -> dict[str, object]:
    return _call(READ_TOOL, {"capability": capability.value, "arguments": {"payload": payload}})


@pytest.fixture
def rt(disposable_database: str) -> Iterator[ScheduleRuntime]:
    runtime = ScheduleRuntime(disposable_database)
    try:
        yield runtime
    finally:
        runtime.close()


class Scene:
    def __init__(self, rt: ScheduleRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
        self.world: World = rt.world(PRINCIPAL, "schedfac")
        self.first = rt.publish(
            monkeypatch, self.world, [Activity("A-1"), Activity("B-2")], data_date=date(2026, 5, 4)
        )
        self.series = rt.scalar(
            "SELECT series_id FROM knowledge.schedule_publications WHERE publication_id = :p",
            p=self.first,
        )
        self.second = rt.publish(
            monkeypatch,
            self.world,
            [Activity("A-1", name="Renamed")],
            data_date=date(2026, 6, 1),
            series_id=self.series,
        )
        listed = rt.ok(ListScheduleActivities(publication_id=self.first))["activities"]
        self.activity = listed[0]["schedule_activity_id"]

    def payloads(self) -> dict[Capability, dict[str, Any]]:
        return {
            Capability.SCHEDULE_SERIES_LIST: {"project_id": self.world.project},
            Capability.SCHEDULE_PUBLICATIONS_LIST: {"series_id": self.series},
            Capability.SCHEDULE_PUBLICATIONS_READ: {"publication_id": self.first},
            Capability.SCHEDULE_ACTIVITIES_LIST: {"publication_id": self.first},
            Capability.SCHEDULE_ACTIVITIES_HISTORY: {"schedule_activity_id": self.activity},
            Capability.SCHEDULE_CHANGES_LIST: {
                "from_publication_id": self.first,
                "to_publication_id": self.second,
            },
        }

    def import_payload(self, rt: ScheduleRuntime) -> dict[str, Any]:
        object_id, version_id = rt.source_object(self.world)
        return {
            "project_id": self.world.project,
            "series_name": "Facade Schedule",
            "enrollment_id": self.world.enrollment,
            "source_object_id": object_id,
            "source_version_id": version_id,
            "publication_role": "update",
        }


@pytest.fixture
def scene(rt: ScheduleRuntime, monkeypatch: pytest.MonkeyPatch) -> Scene:
    return Scene(rt, monkeypatch)


def test_describe_lists_exactly_the_eligible_schedule_reads(rt: ScheduleRuntime) -> None:
    app = _app(rt.service, {"client": _context(_grant(*SEVEN))})
    listed, exact, tools = _run(
        app,
        [
            ("client", _call(DESCRIBE_TOOL, {"feature": "schedule", "limit": 100})),
            ("client", _call(DESCRIBE_TOOL, {"capability": "schedule_changes.list"})),
            ("client", _list_tools()),
        ],
    )
    _failed, catalog = _result(listed)
    items = {item["capability"]: item for item in catalog["items"]}
    assert set(items) == {capability.value for capability in READS}
    summaries = {tool.name: tool.description for tool in TOOLS}
    for name, item in items.items():
        assert item["summary"] == summaries[name], name
        assert item["summary"], name
        assert item["feature"] == "schedule", name
        assert item["kind"] == facade_kind(Capability(name)) == "read", name
        assert item["idempotent"] is False, name
    _failed, contract = _result(exact)
    payload = contract["input_schema"]["properties"]["payload"]["properties"]
    assert set(payload) == {
        "from_publication_id",
        "to_publication_id",
        "change_kind",
        "page_size",
        "cursor",
    }
    assert payload["change_kind"]["enum"][0] == "added"
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert names == {DESCRIBE_TOOL, READ_TOOL}


def test_read_wrapper_invokes_schedule_reads_strictly(rt: ScheduleRuntime, scene: Scene) -> None:
    app = _app(rt.service, {"client": _context(_grant(*READS))})
    payloads = scene.payloads()
    answers = _run(
        app, [("client", _read(capability, payloads[capability])) for capability in READS]
    )
    served = dict(zip(READS, (_ok(answer) for answer in answers), strict=True))
    assert served[Capability.SCHEDULE_SERIES_LIST]["series"][0]["series_id"] == scene.series
    assert [
        p["publication_id"] for p in served[Capability.SCHEDULE_PUBLICATIONS_LIST]["publications"]
    ] == [
        scene.second,
        scene.first,
    ]
    assert served[Capability.SCHEDULE_PUBLICATIONS_READ]["status"] == "complete"
    assert len(served[Capability.SCHEDULE_ACTIVITIES_LIST]["activities"]) == 2
    assert len(served[Capability.SCHEDULE_ACTIVITIES_HISTORY]["observations"]) == 2
    kinds = {c["change_kind"] for c in served[Capability.SCHEDULE_CHANGES_LIST]["changes"]}
    assert kinds == {"renamed", "removed"}
    # A write grant publishes `my_pa.write` too, so the wrong wrapper reaches
    # the facade's own kind check rather than an unpublished tool.
    refusals = _run(
        _app(rt.service, {"client": _context(_grant(*READS, Capability.CAPTURE_CREATE))}),
        [
            (
                "client",
                _read(
                    Capability.SCHEDULE_PUBLICATIONS_READ,
                    {**payloads[Capability.SCHEDULE_PUBLICATIONS_READ], "extra": 1},
                ),
            ),
            (
                "client",
                _call(
                    WRITE_TOOL,
                    {
                        "capability": Capability.SCHEDULE_SERIES_LIST.value,
                        "arguments": {"payload": payloads[Capability.SCHEDULE_SERIES_LIST]},
                    },
                ),
            ),
        ],
    )
    for answer in refusals:
        assert _refusal(answer)[0] == "invalid_request"


@pytest.mark.parametrize(
    "options",
    [{}, {"relationship_grant_profile": "remote.operator"}, {"compact_operator_publication": True}],
    ids=["default", "remote_operator", "compact_operator"],
)
def test_import_is_absent_from_every_publication(
    rt: ScheduleRuntime, scene: Scene, options: dict[str, Any]
) -> None:
    app = _app(rt.service, {"client": _context(_grant(*SEVEN), **options)})
    payload = scene.import_payload(rt)
    before = cpm_snapshot(rt.engine)
    listed, described, *calls, tools = _run(
        app,
        [
            ("client", _call(DESCRIBE_TOOL, {"limit": 100})),
            ("client", _call(DESCRIBE_TOOL, {"capability": IMPORT.value})),
            *[
                (
                    "client",
                    _call(wrapper, {"capability": IMPORT.value, "arguments": {"payload": payload}}),
                )
                for wrapper in (READ_TOOL, WRITE_TOOL, OPERATOR_TOOL)
            ],
            ("client", _list_tools()),
        ],
    )
    _failed, catalog = _result(listed)
    seen = {item["capability"] for item in catalog["items"]}
    assert IMPORT.value not in seen
    assert {capability.value for capability in READS} <= seen
    assert _refusal(described) == ("unsupported", [])
    for answer in calls:
        assert _refusal(answer) == ("unsupported", [])
    assert IMPORT.value not in {tool["name"] for tool in tools["result"]["tools"]}
    assert cpm_snapshot(rt.engine) == before


def test_switch_off_hides_every_schedule_name(rt: ScheduleRuntime, scene: Scene) -> None:
    off = ScheduleRuntime(rt.url, enabled=False)
    try:
        app = _app(off.service, {"client": _context(_grant(*SEVEN))})
        payloads = scene.payloads()
        listed, *answers = _run(
            app,
            [
                ("client", _call(DESCRIBE_TOOL, {"feature": "schedule", "limit": 100})),
                *[("client", _read(capability, payloads[capability])) for capability in READS],
            ],
        )
        # No Schedule name is eligible, and with nothing else granted the facade
        # publishes nothing: describe itself is unsupported, like every read.
        assert _refusal(listed) == ("unsupported", [])
        for answer in answers:
            assert _refusal(answer) == ("unsupported", [])
        assert not SEVEN & set(off.service.available_capabilities)
    finally:
        off.close()


def test_profile_service_composes_no_schedule_capability(rt: ScheduleRuntime) -> None:
    """T2-25: a restricted MCP database profile role holds no CPM privilege.

    The gateway composes the Schedule factory only without an injected
    `data_engine`, so a profile service serves no Schedule name even with the
    switch on; the full-role control service serves all 7.
    """
    settings = Settings(database_url=rt.url, schedule_enabled=True)
    control = build_gateway_runtime(settings)
    profile = build_gateway_runtime(
        settings,
        data_engine=rt.engine,
        independent_audit_engine=control.audit_engine,
        controls_engine=control.work_engine,
        permit_reenrichment=False,
        permit_managed_documents=False,
    )
    try:
        assert set(control.service.available_capabilities) >= SEVEN
        assert not set(profile.service.available_capabilities) & SEVEN
    finally:
        for engine in {control.work_engine, control.audit_engine}:
            engine.dispose()


def test_manifest_and_web_fixture_agree_for_schedule(rt: ScheduleRuntime) -> None:
    served = rt.ok(GetCapabilities(), purpose=Purpose.STATUS_OBSERVATION)["manifest"][
        "capabilities"
    ]
    rows = {row["name"]: row for row in served}
    assert set(rows) >= _SEVEN_NAMES
    for name in _SEVEN_NAMES:
        assert rows[name]["operator_only"] is is_operator_only(Capability(name)), name
        assert rows[name]["availability"] == "available", name
    assert rows[IMPORT.value]["operator_only"] is True
    fixtures = json.loads(
        (_WEB / "lib" / "api" / "decode" / "fixtures" / "python" / "success.json").read_text(
            encoding="utf-8"
        )
    )
    committed = {
        row["name"]: row for row in fixtures["capabilities.get"]["manifest"]["capabilities"]
    }
    assert set(committed) == set(rows)
    for name in _SEVEN_NAMES:
        assert committed[name]["operator_only"] is rows[name]["operator_only"], name
    # No Schedule name is a web route.
    gateway = json.loads((_WEB / "contracts" / "gateway.json").read_text(encoding="utf-8"))
    assert not _SEVEN_NAMES & set(gateway["capabilities"])
    # The committed fixture's composition reports the 2 planes it always did.
    assert [plane["plane"] for plane in fixtures["capabilities.get"]["worker_planes"]] == [
        "capture",
        "enrollment",
    ]


def test_a_chatllm_client_with_v11_grants_reaches_the_reads(
    rt: ScheduleRuntime, scene: Scene
) -> None:
    implemented = frozenset(Capability)
    planes = ChatLLMCompositionPlanes(
        managed_documents=False,
        relationship_intelligence=False,
        relationship_intelligence_writes=False,
        relationship_memory=False,
        constraints=False,
        schedule=True,
    )
    composed = composed_capabilities(implemented, planes)
    now = datetime(2026, 10, 31, 12, tzinfo=UTC)
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
    assert {capability for capability, _ in provisioned} >= set(READS)
    assert IMPORT not in {capability for capability, _ in provisioned}
    app = _app(rt.service, {"chatllm": _context(provisioned, "synthetic-chatllm-client")})
    payloads = scene.payloads()
    listed, *answers, refused = _run(
        app,
        [
            ("chatllm", _call(DESCRIBE_TOOL, {"feature": "schedule", "limit": 100})),
            *[("chatllm", _read(capability, payloads[capability])) for capability in READS],
            (
                "chatllm",
                _call(
                    OPERATOR_TOOL,
                    {
                        "capability": IMPORT.value,
                        "arguments": {"payload": scene.import_payload(rt)},
                    },
                ),
            ),
        ],
    )
    _failed, catalog = _result(listed)
    assert {item["capability"] for item in catalog["items"]} == {c.value for c in READS}
    for answer in answers:
        assert _ok(answer)
    assert _refusal(refused) == ("unsupported", [])
