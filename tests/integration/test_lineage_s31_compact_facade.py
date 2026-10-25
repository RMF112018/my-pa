"""Record lineage S3.1 Part D: lineage end to end through the compact MCP facade (database).

S3.1 contract section 7.13 (worker N3). The real remote MCP app
(`create_remote_mcp_app`, driven in process over httpx's ASGI transport) over
a real `ApplicationService` on PostgreSQL, on the **default remote path**: the
full-role service, a synthetic remote client, compact publication on, the
lineage switch on, remote writes on and durable grants on the named
capabilities. Rows (a)-(f):

(a) `my_pa.describe` lists exactly the eligible lineage names with their
    summary, kind, feature and `idempotent`, and none that is not admitted;
(b) `my_pa.read` / `my_pa.write` invoke lineage capabilities with the canonical
    strict schema, each write recorded `client_identified` with the client id;
(c) the wrong wrapper is `invalid_request`;
(d) a lineage name not admitted is absent from describe and `unsupported` at
    call, answered exactly like a nonexistent name;
(e) the interaction log records each facade call under its canonical target;
(f) `capabilities.get`, the committed `success.json` and `gateway.json` agree.

Beside them: 2 clients asserting one identity reach the identity rule
(`created: false`), the #339 restricted-profile path fails closed for an
opted-in lineage write (section 7.11), and a ChatLLM client holding only its
planner-provisioned grants reaches no lineage name (R31-F08).

Every identity and every body here is synthetic.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx2
import pytest
from sqlalchemy import Engine, event, text

from my_pa.adapters.mcp.chatllm_gateway import (
    DESCRIBE_TOOL,
    OPERATOR_TOOL,
    READ_TOOL,
    WRITE_TOOL,
    facade_kind,
)
from my_pa.adapters.mcp.remote import MCP_PATH, RemoteAccessContext, create_remote_mcp_app
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.mcp_interaction_capture import InteractionRecorder, McpInteractionCapture
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    ChatLLMProfileOutcome,
    chatllm_grant_purpose,
    composed_capabilities,
    desired_effective_capabilities,
    diff_chatllm_data_profile,
    plan_chatllm_grant_actions,
)
from my_pa.application.commands import GetCapabilities
from my_pa.application.service import _LINEAGE_CAPABILITIES
from my_pa.bootstrap.gateway import build_gateway_runtime
from my_pa.bootstrap.mcp_database_profiles import McpDatabaseServices
from my_pa.bootstrap.settings import Settings
from my_pa.domain.identity.operation import Capability, is_operator_only
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.lineage.vocabulary import (
    AcceptanceBasis,
    LinkLifecycleState,
    LinkRevisionAction,
    RelationType,
)
from my_pa.domain.program.vocabulary import PROGRAM_REPORTING_CAPABILITIES
from my_pa.infrastructure.database.engine import create_database_engine
from tests.database.lineage_issue_harness import PRINCIPAL
from tests.database.lineage_record_harness import all_lineage_counts
from tests.database.lineage_s3_harness import corroborates
from tests.database.lineage_s3_read_harness import READS, Grants, grant
from tests.database.lineage_s31_harness import GATEWAY, S31Runtime

pytestmark = pytest.mark.database

_ROOT: Final = Path(__file__).resolve().parents[2]
_WEB: Final = _ROOT / "web" / "src"
CLIENT: Final = "synthetic-facade-client-0001"
OTHER: Final = "synthetic-facade-client-0002"
_HEADERS: Final = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
_FACADE: Final = frozenset({READ_TOOL, WRITE_TOOL, OPERATOR_TOOL})
#: The lineage capabilities this client is granted (section 7.13 (b)).
_GRANTED: Final = (
    "records.lineage.related",
    "issues.closure_readiness",
    "records.associations.assert",
    "issues.memberships.add",
    # Granted, but operator kind: never published remotely (section 7.13 (d)).
    "issues.close",
    "records.associations.confirm",
)
#: Every lineage-plane name (section 7.13: 34 lineage and 7 S4 names).
_LINEAGE_PLANE: Final = frozenset(
    {capability.value for capability in _LINEAGE_CAPABILITIES} | PROGRAM_REPORTING_CAPABILITIES
)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S31Runtime]:
    composed = S31Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _principal() -> Principal:
    return Principal(principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True)


def _grants(*names: str) -> Grants:
    """The named capabilities and every lineage family read (S3 section 6.4)."""
    return grant(*names, *READS)


def _context(grants: Grants, client: str = CLIENT) -> RemoteAccessContext:
    return RemoteAccessContext(
        _principal(),
        allowed_capabilities=frozenset(capability.value for capability, _ in grants),
        capability_purposes=grants,
        compact_publication=True,
        authenticated_client_id=client,
    )


def _app(service: Any, contexts: Mapping[str, RemoteAccessContext], **kwargs: Any) -> Any:  # noqa: ANN401
    """The real remote app; `Bearer <name>` resolves to `contexts[name]`."""

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
        **kwargs,
    )


def _call(name: str, arguments: object, request_id: int = 1) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


async def _exchange(asgi: Any, app: Any, requests: list[tuple[str, object]]) -> list[Any]:  # noqa: ANN401
    answers: list[Any] = []
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=asgi), base_url="http://testserver"
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


def _run(app: Any, requests: list[tuple[str, object]], *, asgi: Any = None) -> list[Any]:  # noqa: ANN401
    return asyncio.run(_exchange(asgi if asgi is not None else app, app, requests))


def _result(answer: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    """`(is_error, document)` of one `tools/call` answer."""
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


def _write(capability: str, payload: dict[str, Any]) -> dict[str, object]:
    return _call(WRITE_TOOL, {"capability": capability, "arguments": {"payload": payload}})


def _read(capability: str, payload: dict[str, Any]) -> dict[str, object]:
    return _call(READ_TOOL, {"capability": capability, "arguments": {"payload": payload}})


def _scene(runtime: S31Runtime, key: str) -> dict[str, str]:
    issue = runtime.ok(_create_issue(f"facade-{key}"), surface=GATEWAY)["issue"]["issue_id"]
    meeting_id, note_id = runtime.note(f"facade-{key}")
    return {
        "issue": str(issue),
        "task": runtime.task(f"facade-{key}-a"),
        "other": runtime.task(f"facade-{key}-b"),
        "meeting": meeting_id,
        "note": note_id,
    }


def _create_issue(key: str) -> Any:  # noqa: ANN401
    from my_pa.application.commands import CreateIssue

    return CreateIssue(title=f"Synthetic issue {key}", idempotency_key=f"s31-facade-{key}")


def _assert_payload(scene: Mapping[str, str], **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    """`records.associations.assert` of `blocks` task -> other, as a remote document."""
    return {
        "relation_type": "blocks",
        "from_record": {"family": "task", "record_id": scene["task"]},
        "to_record": {"family": "task", "record_id": scene["other"]},
        "evidence_anchors": [corroborates(scene["meeting"], scene["note"])],
        **extra,
    }


def _membership_payload(scene: Mapping[str, str]) -> dict[str, Any]:
    return {
        "issue_id": scene["issue"],
        "member": {"family": "task", "record_id": scene["task"]},
        "role": "reference",
        "evidence_anchors": [],
        "user_directed": True,
    }


def _revision_rows(engine: Engine) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT source_capability, acceptance_basis, authority_class,"
                    " decision_channel, asserting_client_id, user_directed_claim"
                    " FROM knowledge.record_link_revisions ORDER BY recorded_at"
                )
            )
        ]


# ---- (a) describe ----------------------------------------------------------------------


def test_describe_lists_exactly_the_eligible_lineage_capabilities(runtime: S31Runtime) -> None:
    app = _app(runtime.service, {"client": _context(_grants(*_GRANTED))})
    listed, exact, tools = _run(
        app,
        [
            ("client", _call(DESCRIBE_TOOL, {"feature": "lineage", "limit": 100})),
            ("client", _call(DESCRIBE_TOOL, {"capability": "records.associations.assert"})),
            ("client", {"jsonrpc": "2.0", "id": 9, "method": "tools/list"}),
        ],
    )
    _failed, catalog = _result(listed)
    items = {item["capability"]: item for item in catalog["items"]}
    # The granted lineage names that are not operator kind, and the granted
    # `issues.read` family read (feature `lineage`); nothing else.
    assert set(items) == {
        "records.lineage.related",
        "issues.closure_readiness",
        "records.associations.assert",
        "issues.memberships.add",
        "issues.read",
    }
    summaries = {tool.name: tool.description for tool in TOOLS}
    for name, item in items.items():
        assert item["summary"] == summaries[name], name
        assert item["feature"] == "lineage", name
        assert item["kind"] == facade_kind(Capability(name)), name
        assert item["idempotent"] is (item["kind"] == "write"), name
    assert items["records.associations.assert"]["kind"] == "write"
    assert items["records.lineage.related"]["kind"] == "read"
    # The exact contract lookup: the published remote schema, no server-owned field.
    _failed, contract = _result(exact)
    payload = contract["input_schema"]["properties"]["payload"]["properties"]
    assert "idempotency_key" not in payload
    assert {"from_record", "to_record", "user_directed"} <= set(payload)
    assert contract["annotations"]["idempotent_hint"] is True
    # The facade publishes describe, read and write -- no operator wrapper, since
    # no operator-kind name is eligible for a remote client.
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert names == {DESCRIBE_TOOL, READ_TOOL, WRITE_TOOL}
    # With the lineage switch off, no lineage name is eligible at all.
    off = S31Runtime(
        runtime.engine.url.render_as_string(hide_password=False), lineage_enabled=False
    )
    try:
        (none,) = _run(
            _app(off.service, {"client": _context(_grants(*_GRANTED))}),
            [("client", _call(DESCRIBE_TOOL, {"feature": "lineage", "limit": 100}))],
        )
    finally:
        off.close()
    _failed, empty = _result(none)
    assert empty["items"] == []


# ---- (b) the wrappers invoke strictly ----------------------------------------------------


def test_the_read_and_write_wrappers_invoke_lineage_capabilities_strictly(
    runtime: S31Runtime,
) -> None:
    scene = _scene(runtime, "strict")
    app = _app(runtime.service, {"client": _context(_grants(*_GRANTED))})
    before = all_lineage_counts(runtime.engine)
    refusals = _run(
        app,
        [
            ("client", _write("records.associations.assert", _assert_payload(scene, extra=1))),
            (
                "client",
                _write(
                    "records.associations.assert",
                    _assert_payload(scene, idempotency_key="idk_" + "0" * 32),
                ),
            ),
            (
                "client",
                _write(
                    "records.associations.assert",
                    _assert_payload(scene, acceptance_basis="user_confirmed"),
                ),
            ),
            (
                "client",
                _write(
                    "records.associations.assert",
                    _assert_payload(scene, asserting_client_id="someone-else"),
                ),
            ),
            (
                "client",
                _read("records.lineage.related", {"seeds": [], "unknown": True}),
            ),
        ],
    )
    for answer in refusals:
        assert _refusal(answer)[0] == "invalid_request"
    assert all_lineage_counts(runtime.engine) == before
    # A fresh app: one session manager runs once.
    asserted, member, related, readiness = _run(
        _app(runtime.service, {"client": _context(_grants(*_GRANTED))}),
        [
            ("client", _write("records.associations.assert", _assert_payload(scene))),
            ("client", _write("issues.memberships.add", _membership_payload(scene))),
            (
                "client",
                _read(
                    "records.lineage.related",
                    {"seeds": [{"family": "task", "record_id": scene["task"]}]},
                ),
            ),
            ("client", _read("issues.closure_readiness", {"issue_id": scene["issue"]})),
        ],
    )
    association = _ok(asserted)["association"]
    membership = _ok(member)["membership"]
    for view in (association, membership):
        assert view["acceptance_basis"] == AcceptanceBasis.CLIENT_IDENTIFIED.value
        # A remote reader -- the writer included -- never sees a client id.
        assert view["asserting_client_id"] is None
    assert membership["user_directed_claim"] is True
    assert association["user_directed_claim"] is False
    rows = _revision_rows(runtime.engine)
    assert rows[-2:] == [
        (
            "records.associations.assert",
            "client_identified",
            "ordinary_reviewer",
            "remote_interactive",
            CLIENT,
            False,
        ),
        (
            "issues.memberships.add",
            "client_identified",
            "ordinary_reviewer",
            "remote_interactive",
            CLIENT,
            True,
        ),
    ]
    related_links = {link["link_id"] for link in _ok(related)["links"]}
    assert {association["link_id"], membership["link_id"]} <= related_links
    unreviewed = _ok(readiness)["unreviewed_links"]
    assert membership["link_id"] in {entry["link_id"] for entry in unreviewed}
    assert _ok(readiness)["ready"] is False
    assert RelationType.BLOCKS.value == association["relation_type"]
    assert LinkLifecycleState.ACTIVE.value == association["lifecycle_state"]


# ---- (c) the wrong wrapper -----------------------------------------------------------------


def test_the_wrong_wrapper_is_refused(runtime: S31Runtime) -> None:
    scene = _scene(runtime, "wrong")
    app = _app(runtime.service, {"client": _context(_grants(*_GRANTED))})
    before = all_lineage_counts(runtime.engine)
    write_as_read, read_as_write = _run(
        app,
        [
            (
                "client",
                _call(
                    READ_TOOL,
                    {
                        "capability": "records.associations.assert",
                        "arguments": {"payload": _assert_payload(scene)},
                    },
                ),
            ),
            (
                "client",
                _call(
                    WRITE_TOOL,
                    {
                        "capability": "records.lineage.related",
                        "arguments": {
                            "payload": {"seeds": [{"family": "task", "record_id": scene["task"]}]}
                        },
                    },
                ),
            ),
        ],
    )
    assert _refusal(write_as_read)[0] == "invalid_request"
    assert _refusal(read_as_write)[0] == "invalid_request"
    assert all_lineage_counts(runtime.engine) == before


# ---- (d) not admitted is absent ------------------------------------------------------------


def test_a_non_admitted_lineage_name_is_absent_and_refused_like_a_nonexistent_one(
    runtime: S31Runtime,
) -> None:
    scene = _scene(runtime, "absent")
    app = _app(runtime.service, {"client": _context(_grants(*_GRANTED))})
    # Not granted, operator kind though granted, and a name that does not exist.
    names = (
        "records.lineage",
        "records.associations.end",
        "issues.close",
        "records.associations.confirm",
        "records.backfill.plan",
        "records.nonexistent",
    )
    requests: list[tuple[str, object]] = [
        ("client", _call(DESCRIBE_TOOL, {"limit": 100})),
    ]
    for name in names:
        requests.append(("client", _call(DESCRIBE_TOOL, {"capability": name})))
        for wrapper in (READ_TOOL, WRITE_TOOL, OPERATOR_TOOL):
            requests.append(
                (
                    "client",
                    _call(
                        wrapper,
                        {
                            "capability": name,
                            "arguments": {"payload": {"issue_id": scene["issue"]}},
                        },
                    ),
                )
            )
    listed, *answers = _run(app, requests)
    _failed, catalog = _result(listed)
    listed_names = {item["capability"] for item in catalog["items"]}
    assert not listed_names & set(names)
    # Every refusal -- describe and every wrapper, every name -- is the one a
    # nonexistent name gets: `unsupported`, no detail, the same message.
    problems = [_result(answer)[1] for answer in answers]
    assert {
        (problem["code"], tuple(problem.get("safe_details") or ()), problem["message"])
        for problem in (document.get("error", document) for document in problems)
    } == {("unsupported", (), problems[-1].get("error", problems[-1])["message"])}


# ---- (e) interaction capture -------------------------------------------------------------


def test_facade_calls_are_captured_under_their_canonical_target(runtime: S31Runtime) -> None:
    scene = _scene(runtime, "capture")
    app = _app(runtime.service, {"client": _context(_grants(*_GRANTED))})
    rows: list[Mapping[str, object]] = []
    recorder = InteractionRecorder(rows.append, facade_invoke_tools=_FACADE, stderr=io.StringIO())
    recorder.start()
    try:
        _run(
            app,
            [
                ("client", _write("records.associations.assert", _assert_payload(scene))),
                (
                    "client",
                    _read(
                        "records.lineage.related",
                        {"seeds": [{"family": "task", "record_id": scene["task"]}]},
                    ),
                ),
                ("client", _call(DESCRIBE_TOOL, {"feature": "lineage"})),
            ],
            asgi=McpInteractionCapture(app, recorder, path=MCP_PATH),
        )
    finally:
        recorder.stop(timeout=5)
    assert recorder.dropped == recorder.write_failures == recorder.capture_errors == 0
    captured = [
        (row["tool_name"], row["capability"], row["outcome"], row["oauth_client_id"])
        for row in rows
    ]
    assert captured == [
        (WRITE_TOOL, "records.associations.assert", "ok", CLIENT),
        (READ_TOOL, "records.lineage.related", "ok", CLIENT),
        (DESCRIBE_TOOL, DESCRIBE_TOOL, "ok", CLIENT),
    ]


# ---- (f) the manifest and the web fixtures agree --------------------------------------------


def test_the_capability_manifest_and_web_fixtures_agree_for_lineage(runtime: S31Runtime) -> None:
    served = runtime.ok(GetCapabilities())["manifest"]["capabilities"]
    rows = {row["name"]: row for row in served}
    assert set(rows) >= _LINEAGE_PLANE
    assert len(_LINEAGE_PLANE) == 41
    for name in _LINEAGE_PLANE:
        assert rows[name]["operator_only"] is is_operator_only(Capability(name)), name
    # Through the facade too, for a client granted `capabilities.get`.
    app = _app(runtime.service, {"client": _context(_grants("capabilities.get"))})
    (remote,) = _run(app, [("client", _read("capabilities.get", {}))])
    remote_rows = {row["name"]: row for row in _ok(remote)["manifest"]["capabilities"]}
    for name in _LINEAGE_PLANE:
        assert remote_rows[name]["operator_only"] is rows[name]["operator_only"], name
    # The committed success fixture the strict web client decodes says the same.
    fixtures = json.loads(
        (_WEB / "lib" / "api" / "decode" / "fixtures" / "python" / "success.json").read_text(
            encoding="utf-8"
        )
    )
    committed = {
        row["name"]: row for row in fixtures["capabilities.get"]["manifest"]["capabilities"]
    }
    assert set(committed) == set(rows)
    for name in _LINEAGE_PLANE:
        assert committed[name]["operator_only"] is rows[name]["operator_only"], name
    # `gateway.json` keeps its 110 entries; no lineage write is a web route.
    gateway = json.loads((_WEB / "contracts" / "gateway.json").read_text(encoding="utf-8"))
    assert len(gateway["capabilities"]) == 110
    # The lineage decoders' closed sets equal the server vocabulary.
    decoder = (_WEB / "lib" / "api" / "decode" / "capabilities" / "records.lineage.ts").read_text(
        encoding="utf-8"
    )
    found = re.search(r"export const ACCEPTANCE_BASES = \[([^\]]*)\]", decoder)
    assert found is not None
    assert set(re.findall(r'"([a-z_]+)"', found.group(1))) == {
        member.value for member in AcceptanceBasis
    }
    timeline = (_WEB / "components" / "issues" / "issue-timeline.tsx").read_text(encoding="utf-8")
    assert f"{LinkRevisionAction.CONFIRM.value}:" in timeline


# ---- 2 clients, one identity --------------------------------------------------------------


def test_two_clients_asserting_one_identity_get_created_false_not_conflict(
    runtime: S31Runtime,
) -> None:
    scene = _scene(runtime, "two")
    contexts = {
        "first": _context(_grants(*_GRANTED), CLIENT),
        "second": _context(_grants(*_GRANTED), OTHER),
    }
    first, second, again = _run(
        _app(runtime.service, contexts),
        [
            ("first", _write("records.associations.assert", _assert_payload(scene))),
            ("second", _write("records.associations.assert", _assert_payload(scene))),
            ("second", _write("records.associations.assert", _assert_payload(scene))),
        ],
    )
    created, answered, replayed = _ok(first), _ok(second), _ok(again)
    assert (created["created"], created["replayed"]) == (True, False)
    # The second client's key is its own: the identity rule answers, not a conflict.
    assert (answered["created"], answered["replayed"]) == (False, False)
    assert answered["association"]["link_id"] == created["association"]["link_id"]
    # Its own retry derives its own key and replays.
    assert (replayed["created"], replayed["replayed"]) == (False, True)
    with runtime.engine.connect() as connection:
        writers = connection.execute(
            text(
                "SELECT asserting_client_id FROM knowledge.lineage_write_requests"
                " WHERE capability = 'records.associations.assert' ORDER BY created_at"
            )
        ).scalars()
        assert list(writers)[-2:] == [CLIENT, OTHER]


# ---- the #339 restricted-profile path (section 7.11) ------------------------------------


def _privilege_less_engine(url: str) -> Engine:
    """An engine whose sessions act as `pg_read_all_data`: it reads, and writes nothing.

    The fixed MCP data roles hold no privilege on any lineage table (no reviewed
    `McpObjectGrant` names one, S4 D-46); a predefined read-only role stands in
    for them without creating a role in the cluster.
    """
    engine = create_database_engine(url, statement_timeout_ms=30_000)

    @event.listens_for(engine, "connect")
    def act_as_reader(connection: Any, _record: Any) -> None:  # noqa: ANN401
        cursor = connection.cursor()
        cursor.execute("SET ROLE pg_read_all_data")
        cursor.close()

    return engine


def test_an_opted_in_lineage_write_on_a_profile_service_fails_closed_and_writes_nothing(
    runtime: S31Runtime,
) -> None:
    scene = _scene(runtime, "profile")
    url = runtime.engine.url.render_as_string(hide_password=False)
    settings = Settings(database_url=url, lineage_enabled=True)
    control = build_gateway_runtime(settings)
    engines = (_privilege_less_engine(url), _privilege_less_engine(url))
    services = [
        build_gateway_runtime(
            settings,
            data_engine=engine,
            independent_audit_engine=control.audit_engine,
            controls_engine=control.work_engine,
            permit_reenrichment=False,
            permit_managed_documents=False,
        ).service
        for engine in engines
    ]
    profiles = McpDatabaseServices(
        services[0],
        services[1],
        frozenset(),
        frozenset({CLIENT}),
        engines,
        opt_ins=frozenset({"issues.memberships.add", "records.associations.assert", *READS}),
    )
    try:
        granted = _grants("issues.memberships.add", "records.associations.assert")
        routed = profiles.access(_context(granted), write_allowed=True)
        assert routed is not None
        # The opted-in write grant selects the rw service (R31-F04).
        assert routed.service is services[1]
        assert "issues.memberships.add" in (routed.allowed_capabilities or ())
        before = all_lineage_counts(runtime.engine)
        app = _app(control.service, {"client": routed}, require_bound_service=True)
        (answer,) = _run(
            app, [("client", _write("issues.memberships.add", _membership_payload(scene)))]
        )
        assert _refusal(answer)[0] == "internal_error"
        assert all_lineage_counts(runtime.engine) == before
        # The same opt-in without the profiles composed is no grant: the default
        # profile ceiling names no lineage write.
        default = McpDatabaseServices(
            services[0], services[1], frozenset(), frozenset({CLIENT}), engines
        )
        narrowed = default.access(_context(granted), write_allowed=True)
        assert narrowed is not None
        assert not (narrowed.allowed_capabilities or frozenset()) & _LINEAGE_PLANE
    finally:
        profiles.close()
        control_engines = {control.work_engine, control.audit_engine}
        for engine in control_engines:
            engine.dispose()


# ---- the ChatLLM gateway path (R31-F08) --------------------------------------------------


def test_a_chatllm_client_sees_and_reaches_no_lineage_capability(runtime: S31Runtime) -> None:
    scene = _scene(runtime, "chatllm")
    implemented = frozenset(Capability)
    planes = ChatLLMCompositionPlanes(
        managed_documents=True,
        relationship_intelligence=True,
        relationship_intelligence_writes=True,
        relationship_memory=True,
        constraints=True,
        knowledge_assertions=True,
    )
    composed = composed_capabilities(implemented, planes)
    # The planner provisions exactly its desired names, each for its purpose.
    actions = plan_chatllm_grant_actions(
        diff_chatllm_data_profile(
            implemented=implemented,
            composed=composed,
            grants=(),
            now=_now(),
            resource="http://testserver",
            scope="my-pa.read",
        ),
        (),
        now=_now(),
        resource="http://testserver",
        scope="my-pa.read",
    )
    provisioned: Grants = frozenset(
        (action.capability, action.purpose) for action in actions if action.kind == "add"
    )
    assert provisioned
    lineage_plane = {Capability(name) for name in _LINEAGE_PLANE}
    assert not {capability for capability, _ in provisioned} & lineage_plane
    diff = diff_chatllm_data_profile(
        implemented=implemented,
        composed=composed,
        grants=(),
        now=_now(),
        resource="http://testserver",
        scope="my-pa.read",
    )
    assert not diff.desired_effective & lineage_plane
    assert not diff.add & lineage_plane
    for capability in lineage_plane:
        assert diff.outcomes[capability] in {
            ChatLLMProfileOutcome.EXCLUDED,
            ChatLLMProfileOutcome.POLICY_REQUIRED_NOT_IMPLEMENTED,
        }, capability
        assert (
            diff.outcomes[capability]
            is not ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_MISSING
        )
    assert not desired_effective_capabilities(composed, knowledge_manager=True) & lineage_plane
    app = _app(runtime.service, {"chatllm": _context(provisioned, "synthetic-chatllm-client")})
    listed, *calls = _run(
        app,
        [
            ("chatllm", _call(DESCRIBE_TOOL, {"limit": 100})),
            (
                "chatllm",
                _read(
                    "records.lineage.related",
                    {"seeds": [{"family": "task", "record_id": scene["task"]}]},
                ),
            ),
            ("chatllm", _write("records.associations.assert", _assert_payload(scene))),
            ("chatllm", _write("issues.memberships.add", _membership_payload(scene))),
            ("chatllm", _call(DESCRIBE_TOOL, {"capability": "records.lineage.related"})),
        ],
    )
    _failed, catalog = _result(listed)
    seen = {item["capability"] for item in catalog["items"]}
    assert seen, "the ChatLLM client sees its data profile"
    assert not seen & _LINEAGE_PLANE
    assert {item["feature"] for item in catalog["items"]}.isdisjoint({"lineage", "programs"})
    for answer in calls:
        assert _refusal(answer) == ("unsupported", [])
    # Every provisioned grant names its capability's one ChatLLM purpose.
    assert all(purpose is chatllm_grant_purpose(capability) for capability, purpose in provisioned)


def _now() -> datetime:
    return datetime(2026, 10, 25, 12, tzinfo=UTC)
