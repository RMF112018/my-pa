"""Record lineage P1: lineage end to end for a v10-provisioned client (database).

Client exposure contract (`docs/architecture/record-lineage-client-exposure-contract.md`)
sections 5 and 10, row "Client path end to end". The real remote MCP app
(`create_remote_mcp_app`, driven in process over httpx's ASGI transport) over a
real `ApplicationService` on PostgreSQL, on the **default remote path**: the
full-role service with the lineage and Program-reporting switches on, the
entity and Constraint planes composed, and a synthetic remote client whose
grants are exactly what the `chatllm-data-v10` planner provisions for those
planes (or, where stated, exactly the 34 client-usable lineage-plane names).

The module re-runs the S3.1 guards on this path (contract section 5.3): the
server-derived client id, the `client_identified` default, the unverified
`user_directed` claim, accepted lineage kept, per-client budgets, façade
eligibility, the operator kind of the attested names, the lineage switch, the
close gate's review scope, hidden-is-absent and the write-grant re-check.

Every identity and every body here is synthetic.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any, Final

import httpx2
import pytest
from sqlalchemy import Engine, text

from my_pa.adapters.mcp.chatllm_gateway import (
    DESCRIBE_TOOL,
    OPERATOR_TOOL,
    READ_TOOL,
    WRITE_TOOL,
)
from my_pa.adapters.mcp.remote import MCP_PATH, RemoteAccessContext, create_remote_mcp_app
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    composed_capabilities,
    diff_chatllm_data_profile,
    plan_chatllm_grant_actions,
)
from my_pa.application.commands import (
    AddIssueMembership,
    Command,
    ConfirmIssueMembership,
    CreateIssue,
    EndIssueMembership,
    EndRecordAssociation,
)
from my_pa.application.service import _HANDLERS, _LINEAGE_CAPABILITIES
from my_pa.bootstrap.gateway import build_gateway_runtime
from my_pa.bootstrap.settings import Settings
from my_pa.domain.identity.operation import Capability, is_write_capability
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.lineage.vocabulary import (
    ATTESTED_LINEAGE_WRITE_CAPABILITIES,
    CLIENT_LINEAGE_WRITES_PER_HOUR,
    LINEAGE_BACKFILL_CAPABILITIES,
)
from my_pa.domain.program.vocabulary import PROGRAM_REPORTING_CAPABILITIES
from my_pa.infrastructure.database.engine import create_database_engine
from tests.database.lineage_issue_harness import PRINCIPAL
from tests.database.lineage_record_harness import (
    NOTE_BODY,
    all_lineage_counts,
    note_anchor,
    originated_from,
)
from tests.database.lineage_s2_harness import assertion, close, work_task
from tests.database.lineage_s3_harness import contradicts, corroborates
from tests.database.lineage_s3_read_harness import Grants, grant
from tests.database.lineage_s4_harness import T0
from tests.database.lineage_s31_harness import (
    GATEWAY,
    S31ReportRuntime,
    S31Runtime,
    completed_requests,
    seed_completed_requests,
)

pytestmark = pytest.mark.database

CHATLLM: Final = "synthetic-p1-chatllm-client"
CHATGPT: Final = "synthetic-p1-chatgpt-client"
_REMOTE: Final = "remote_interactive"
_HEADERS: Final = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
_RESOURCE: Final = "http://testserver"
_SCOPE: Final = "my-pa.read"

#: The 7 withheld names (contract section 3).
WITHHELD: Final = frozenset(ATTESTED_LINEAGE_WRITE_CAPABILITIES | LINEAGE_BACKFILL_CAPABILITIES)
#: Every lineage-plane name: the 34 lineage and the 7 S4 names.
LINEAGE_PLANE: Final = (
    frozenset(capability.value for capability in _LINEAGE_CAPABILITIES)
    | PROGRAM_REPORTING_CAPABILITIES
)
#: The 34 client-usable names.
EXPOSED: Final = LINEAGE_PLANE - WITHHELD
EXPOSED_READS: Final = frozenset(
    name for name in EXPOSED if not is_write_capability(Capability(name))
)

#: The planes the v10 planner models for this module's service: every plane but
#: the Knowledge plane, with both lineage switches on.
_V10_PLANES: Final = ChatLLMCompositionPlanes(
    managed_documents=True,
    relationship_intelligence=True,
    relationship_intelligence_writes=True,
    relationship_memory=True,
    constraints=True,
    lineage=True,
    program_reporting=True,
)


def _now() -> datetime:
    return datetime(2026, 10, 26, 12, tzinfo=UTC)


def v10_grants(planes: ChatLLMCompositionPlanes = _V10_PLANES) -> Grants:
    """Exactly what the `chatllm-data-v10` planner adds for a client holding nothing."""
    implemented = frozenset(_HANDLERS)
    composed = composed_capabilities(implemented, planes)
    diff = diff_chatllm_data_profile(
        implemented=implemented,
        composed=composed,
        grants=(),
        now=_now(),
        resource=_RESOURCE,
        scope=_SCOPE,
    )
    actions = plan_chatllm_grant_actions(diff, (), now=_now(), resource=_RESOURCE, scope=_SCOPE)
    assert all(action.kind == "add" for action in actions)
    return frozenset((action.capability, action.purpose) for action in actions)


def only_the_34() -> Grants:
    """Exactly the 34 client-usable names, each under its planner purpose."""
    return frozenset(pair for pair in v10_grants() if pair[0].value in EXPOSED)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S31ReportRuntime]:
    composed = S31ReportRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _url(runtime: S31Runtime) -> str:
    return runtime.engine.url.render_as_string(hide_password=False)


# ---- the remote app ---------------------------------------------------------------


def _context(grants: Grants, client: str = CHATLLM, *, compact: bool = True) -> RemoteAccessContext:
    return RemoteAccessContext(
        Principal(principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True),
        allowed_capabilities=frozenset(capability.value for capability, _ in grants),
        capability_purposes=grants,
        compact_publication=compact,
        authenticated_client_id=client,
    )


def _app(
    service: Any,  # noqa: ANN401
    contexts: Mapping[str, RemoteAccessContext],
    *,
    writes: bool = True,
) -> Any:  # noqa: ANN401
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
        writes_enabled=writes,
        resource=_RESOURCE,
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({_SCOPE}),
    )


def _call(name: str, arguments: object, request_id: int = 1) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
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


def _run(app: Any, requests: list[tuple[str, object]]) -> list[Any]:  # noqa: ANN401
    """One app, one session manager: every request in one run."""
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


def _payload(command: Command, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    """A command as a remote payload: no idempotency key (server-derived), no `None`."""
    fields = {
        key: value
        for key, value in dataclasses.asdict(command).items()  # type: ignore[call-overload]
        if key != "idempotency_key" and value is not None
    }
    document = json.loads(json.dumps(fields, default=str))
    assert isinstance(document, dict)
    return {**document, **extra}


def _write(capability: str, payload: dict[str, Any]) -> dict[str, object]:
    return _call(WRITE_TOOL, {"capability": capability, "arguments": {"payload": payload}})


def _read(capability: str, payload: dict[str, Any]) -> dict[str, object]:
    return _call(READ_TOOL, {"capability": capability, "arguments": {"payload": payload}})


def _describe_all(
    service: Any,  # noqa: ANN401
    context: RemoteAccessContext,
    *,
    writes: bool = True,
) -> set[str]:
    """Every capability `my_pa.describe` lists, page after page (a fresh app per page)."""
    seen: set[str] = set()
    cursor: str | None = None
    while True:
        arguments: dict[str, object] = {"limit": 100}
        if cursor is not None:
            arguments["cursor"] = cursor
        (answer,) = _run(
            _app(service, {"client": context}, writes=writes),
            [("client", _call(DESCRIBE_TOOL, arguments))],
        )
        failed, page = _result(answer)
        assert not failed, page
        seen |= {item["capability"] for item in page["items"]}
        cursor = page["next_cursor"]
        if cursor is None:
            return seen


def _scene(runtime: S31Runtime, key: str) -> dict[str, str]:
    issue = runtime.ok(
        CreateIssue(title=f"Synthetic issue {key}", idempotency_key=f"p1-{key}"), surface=GATEWAY
    )["issue"]["issue_id"]
    meeting_id, note_id = runtime.note(f"p1-{key}")
    return {
        "issue": str(issue),
        "task": runtime.task(f"p1-{key}-a"),
        "other": runtime.task(f"p1-{key}-b"),
        "meeting": meeting_id,
        "note": note_id,
    }


def _blocks(scene: Mapping[str, str], key: str) -> Command:
    return assertion(
        "blocks",
        ("task", scene["task"]),
        ("task", scene["other"]),
        f"p1-{key}",
        (corroborates(scene["meeting"], scene["note"]),),
    )


def _revisions(engine: Engine) -> list[tuple[Any, ...]]:
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


# ---- publication -----------------------------------------------------------------


def test_a_v10_chatllm_client_describes_exactly_the_client_usable_lineage_names(
    runtime: S31ReportRuntime,
) -> None:
    grants = v10_grants()
    granted = {capability.value for capability, _ in grants}
    assert granted >= EXPOSED
    assert not WITHHELD & granted
    assert len(EXPOSED) == 34
    listed = _describe_all(runtime.service, _context(grants))
    assert listed & LINEAGE_PLANE == EXPOSED
    assert not listed & WITHHELD


def test_withheld_lineage_names_are_absent_and_unsupported_for_a_v10_client(
    runtime: S31ReportRuntime,
) -> None:
    # The backfill sub-switch on too, so all 7 are served by the process.
    served = S31Runtime(_url(runtime), lineage_backfill_enabled=True)
    try:
        assert {c.value for c in served.service.available_capabilities} >= WITHHELD
        scene = _scene(served, "withheld")
        # Each withheld name also granted directly, beside the v10 profile.
        grants = v10_grants() | grant(*WITHHELD)
        listed = _describe_all(served.service, _context(grants))
        assert not listed & WITHHELD
        # (This process composes no Program reporting.)
        assert listed & LINEAGE_PLANE == EXPOSED - PROGRAM_REPORTING_CAPABILITIES
        # The canonical catalog of the same client withholds them too.
        (tools,) = _run(
            _app(served.service, {"client": _context(grants, compact=False)}),
            [("client", {"jsonrpc": "2.0", "id": 9, "method": "tools/list"})],
        )
        canonical = {tool["name"] for tool in tools["result"]["tools"]}
        assert not canonical & WITHHELD
        # (This process composes no Program reporting.)
        assert canonical >= EXPOSED - PROGRAM_REPORTING_CAPABILITIES
        requests: list[tuple[str, object]] = []
        for name in sorted(WITHHELD):
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
        before = all_lineage_counts(served.engine)
        answers = _run(_app(served.service, {"client": _context(grants)}), requests)
        assert len(answers) == 4 * len(WITHHELD)
        for answer in answers:
            assert _refusal(answer) == ("unsupported", [])
        assert all_lineage_counts(served.engine) == before
    finally:
        served.close()


def test_with_remote_writes_off_a_v10_client_sees_only_the_lineage_reads(
    runtime: S31ReportRuntime,
) -> None:
    grants = v10_grants()
    assert len(EXPOSED_READS) == 18
    seen = _describe_all(runtime.service, _context(grants), writes=False)
    assert seen & LINEAGE_PLANE == EXPOSED_READS
    scene = _scene(runtime, "writes-off")
    before = all_lineage_counts(runtime.engine)
    (refused,) = _run(
        _app(runtime.service, {"client": _context(grants)}, writes=False),
        [("client", _write("records.associations.assert", _payload(_blocks(scene, "writes-off"))))],
    )
    assert _refusal(refused)[0] == "unsupported"
    assert all_lineage_counts(runtime.engine) == before


def test_the_lineage_switch_off_withholds_every_lineage_name_from_a_v10_client(
    runtime: S31ReportRuntime,
) -> None:
    off = S31Runtime(_url(runtime), lineage_enabled=False)
    try:
        grants = v10_grants()
        listed = _describe_all(off.service, _context(grants))
        assert listed, "the client still sees the rest of its profile"
        assert not listed & LINEAGE_PLANE
        requests: list[tuple[str, object]] = []
        for name in sorted(EXPOSED):
            wrapper = WRITE_TOOL if is_write_capability(Capability(name)) else READ_TOOL
            requests.append(
                ("client", _call(wrapper, {"capability": name, "arguments": {"payload": {}}}))
            )
        answers = _run(_app(off.service, {"client": _context(grants)}), requests)
        for answer in answers:
            assert _refusal(answer) == ("unsupported", [])
    finally:
        off.close()


# ---- provenance ------------------------------------------------------------------


def test_a_v10_chatllm_client_commits_client_identified_lineage_through_the_facade(
    runtime: S31ReportRuntime,
) -> None:
    scene = _scene(runtime, "commit")
    member = AddIssueMembership(
        issue_id=scene["issue"],
        member={"family": "task", "record_id": scene["task"]},
        role="reference",
        idempotency_key="unused",
        evidence_anchors=(),
    )
    asserted, added = _run(
        _app(runtime.service, {"client": _context(v10_grants())}),
        [
            ("client", _write("records.associations.assert", _payload(_blocks(scene, "commit")))),
            (
                "client",
                _write("issues.memberships.add", _payload(member, user_directed=True)),
            ),
        ],
    )
    association = _ok(asserted)["association"]
    membership = _ok(added)["membership"]
    # The claim is stored as a claim only: never an accepted basis.
    for view in (association, membership):
        assert view["acceptance_basis"] == "client_identified"
    assert membership["user_directed_claim"] is True
    assert association["user_directed_claim"] is False
    assert _revisions(runtime.engine)[-2:] == [
        (
            "records.associations.assert",
            "client_identified",
            "ordinary_reviewer",
            _REMOTE,
            CHATLLM,
            False,
        ),
        (
            "issues.memberships.add",
            "client_identified",
            "ordinary_reviewer",
            _REMOTE,
            CHATLLM,
            True,
        ),
    ]


def test_a_v10_client_cannot_supply_provenance_or_a_key_through_the_facade(
    runtime: S31ReportRuntime,
) -> None:
    scene = _scene(runtime, "provenance")
    base = _payload(_blocks(scene, "provenance"))
    before = all_lineage_counts(runtime.engine)
    refusals = _run(
        _app(runtime.service, {"client": _context(v10_grants())}),
        [
            (
                "client",
                _write(
                    "records.associations.assert", {**base, "idempotency_key": "idk_" + "1" * 32}
                ),
            ),
            (
                "client",
                _write(
                    "records.associations.assert", {**base, "acceptance_basis": "user_confirmed"}
                ),
            ),
            (
                "client",
                _write("records.associations.assert", {**base, "asserting_client_id": CHATGPT}),
            ),
            (
                "client",
                _write(
                    "records.associations.assert", {**base, "decision_channel": "local_operator"}
                ),
            ),
            (
                "client",
                _write(
                    "records.associations.assert", {**base, "authority_class": "attested_operator"}
                ),
            ),
        ],
    )
    for answer in refusals:
        assert _refusal(answer)[0] == "invalid_request"
    assert all_lineage_counts(runtime.engine) == before
    # The accepted request records the server-stamped client, never a claimed one.
    (written,) = _run(
        _app(runtime.service, {"client": _context(v10_grants())}),
        [("client", _write("records.associations.assert", base))],
    )
    assert _ok(written)["association"]["acceptance_basis"] == "client_identified"
    assert _revisions(runtime.engine)[-1][3:5] == (_REMOTE, CHATLLM)
    with runtime.engine.connect() as connection:
        writer = connection.execute(
            text(
                "SELECT decision_channel, asserting_client_id FROM knowledge.lineage_write_requests"
                " WHERE capability = 'records.associations.assert' ORDER BY created_at DESC LIMIT 1"
            )
        ).one()
    assert tuple(writer) == (_REMOTE, CHATLLM)


def test_a_v10_client_cannot_revise_accepted_lineage(runtime: S31ReportRuntime) -> None:
    scene = _scene(runtime, "accepted")
    link = runtime.ok(_blocks(scene, "accepted"), surface=GATEWAY)["association"]
    assert link["acceptance_basis"] == "user_confirmed"
    contest = {
        "link_id": link["link_id"],
        "expected_revision": 1,
        "reason": "The source says otherwise.",
        "evidence_anchors": [contradicts(scene["meeting"], scene["note"])],
    }
    end = _payload(
        EndRecordAssociation(
            link_id=link["link_id"],
            expected_revision=2,
            idempotency_key="unused",
            reason="A client ends the accepted link.",
        )
    )
    contested, ended = _run(
        _app(runtime.service, {"client": _context(v10_grants())}),
        [
            ("client", _write("records.associations.contest", contest)),
            ("client", _write("records.associations.end", end)),
        ],
    )
    # 1 contest of an accepted semantic link is admitted (S3.1 section 4.4) ...
    association = _ok(contested)["association"]
    assert (association["lifecycle_state"], association["acceptance_basis"]) == (
        "contested",
        "client_identified",
    )
    # ... and after it the link's history, not its head, keeps it client-immutable.
    assert _refusal(ended) == ("denied", [])
    with runtime.engine.connect() as connection:
        revisions = connection.execute(
            text("SELECT count(*) FROM knowledge.record_link_revisions WHERE link_id = :link"),
            {"link": link["link_id"]},
        ).scalar_one()
    assert revisions == 2


# ---- budgets ---------------------------------------------------------------------


def test_two_remote_clients_keep_separate_client_ids_and_budgets(
    runtime: S31ReportRuntime,
) -> None:
    """A compact ChatLLM client and a canonical ChatGPT-shaped client: 2 buckets."""
    scene = _scene(runtime, "budgets")
    grants = v10_grants()
    contexts = {
        "chatllm": _context(grants, CHATLLM),
        "chatgpt": _context(grants, CHATGPT, compact=False),
    }
    # The ChatLLM bucket is full for the hour; the ChatGPT bucket is empty.
    seed_completed_requests(
        runtime.engine,
        CLIENT_LINEAGE_WRITES_PER_HOUR,
        issue_id=scene["issue"],
        channel=_REMOTE,
        client=CHATLLM,
    )
    before = all_lineage_counts(runtime.engine)
    limited, written = _run(
        _app(runtime.service, contexts),
        [
            ("chatllm", _write("records.associations.assert", _payload(_blocks(scene, "budgets")))),
            (
                "chatgpt",
                _call(
                    "records.associations.assert",
                    {"payload": _payload(_blocks(scene, "budgets"))},
                ),
            ),
        ],
    )
    assert _refusal(limited) == ("rate_limited", ["lineage_write_budget"])
    association = _ok(written)["association"]
    assert association["acceptance_basis"] == "client_identified"
    after = all_lineage_counts(runtime.engine)
    assert after["record_link_revisions"] == before["record_link_revisions"] + 1
    assert _revisions(runtime.engine)[-1][3:5] == (_REMOTE, CHATGPT)
    assert completed_requests(runtime.engine, channel=_REMOTE, client=CHATLLM) == (
        CLIENT_LINEAGE_WRITES_PER_HOUR
    )
    assert completed_requests(runtime.engine, channel=_REMOTE, client=CHATGPT) == 1


# ---- Program reporting on the default path -----------------------------------------


def test_a_v10_client_reads_program_reporting_on_the_default_path(
    runtime: S31ReportRuntime,
) -> None:
    seeds = runtime.seeds
    program = seeds.program("P1 Program")
    _project, entity = seeds.project("P1 member")
    seeds.edge(entity, program, effective_from=T0)
    cycle = runtime.cycle("p1-manifest")
    report_id = runtime.research(cycle, "p1-manifest")
    overview, listed, manifest = _run(
        _app(runtime.service, {"client": _context(v10_grants())}),
        [
            ("client", _read("programs.overview", {"program_entity_ids": [program]})),
            ("client", _read("commitments.v2.list", {})),
            ("client", _read("reports.manifest", {"report_id": report_id})),
        ],
    )
    assert _ok(overview)["programs"][0]["program_entity_id"] == program
    assert "commitments" in _ok(listed)
    assert _ok(manifest)["report_id"] == report_id
    # A restricted-profile composition builds no Program read engine: `programs.*`
    # stay withheld there whatever the switches say (S4 D-46).
    url = _url(runtime)
    settings = Settings(
        database_url=url,
        lineage_enabled=True,
        program_reporting_enabled=True,
        relationship_intelligence_enabled=True,
    )
    control = build_gateway_runtime(settings)
    profile_engine = create_database_engine(url, statement_timeout_ms=30_000)
    try:
        default_served = {c.value for c in control.service.available_capabilities}
        assert {"programs.members.resolve", "programs.overview"} <= default_served
        restricted = build_gateway_runtime(
            settings,
            data_engine=profile_engine,
            independent_audit_engine=control.audit_engine,
            controls_engine=control.work_engine,
            permit_reenrichment=False,
            permit_managed_documents=False,
        ).service
        restricted_served = {c.value for c in restricted.available_capabilities}
        assert not restricted_served & {"programs.members.resolve", "programs.overview"}
    finally:
        profile_engine.dispose()
        for engine in {control.work_engine, control.audit_engine}:
            engine.dispose()


# ---- visibility and grants -------------------------------------------------------


def test_a_34_only_client_sees_a_non_issue_endpoint_as_absent_until_its_family_read_is_granted(
    runtime: S31ReportRuntime,
) -> None:
    scene = _scene(runtime, "only34")
    anchor = note_anchor(scene["meeting"], scene["note"], NOTE_BODY)
    link = _payload(
        originated_from(
            "task", scene["task"], "meeting_note_version", scene["note"], "p1-only34", (anchor,)
        )
    )
    related = {"seeds": [{"family": "task", "record_id": scene["task"]}]}
    work = _payload(work_task(scene["issue"], "p1-only34"))
    only = only_the_34()
    assert len(only) == 34
    before = all_lineage_counts(runtime.engine)
    hidden_link, hidden_related, denied_work = _run(
        _app(runtime.service, {"client": _context(only)}),
        [
            ("client", _write("records.associations.assert", link)),
            ("client", _read("records.lineage.related", related)),
            ("client", _write("issues.work.create_task", work)),
        ],
    )
    # Both endpoints are hidden; each answers exactly as an absent one.
    assert _refusal(hidden_link) in (("not_found", ["from"]), ("not_found", ["to"]))
    assert _refusal(hidden_related)[0] == "not_found"
    assert _refusal(denied_work) == ("denied", [])
    assert all_lineage_counts(runtime.engine) == before
    # The Task and Meeting family reads make both endpoints and the seed visible.
    seeing = only | grant("tasks.read", "meetings.read")
    seen_link, seen_related, still_denied = _run(
        _app(runtime.service, {"client": _context(seeing)}),
        [
            ("client", _write("records.associations.assert", link)),
            ("client", _read("records.lineage.related", related)),
            ("client", _write("issues.work.create_task", work)),
        ],
    )
    association = _ok(seen_link)["association"]
    assert association["acceptance_basis"] == "client_identified"
    assert association["link_id"] in {item["link_id"] for item in _ok(seen_related)["links"]}
    assert _refusal(still_denied) == ("denied", [])
    # The composite needs its native create grant too.
    creating = seeing | grant("tasks.create")
    (created,) = _run(
        _app(runtime.service, {"client": _context(creating)}),
        [("client", _write("issues.work.create_task", work))],
    )
    assert _ok(created)["membership"]["acceptance_basis"] == "client_identified"


def test_a_v10_client_write_without_its_own_grant_is_unsupported(
    runtime: S31ReportRuntime,
) -> None:
    scene = _scene(runtime, "own-grant")
    without = frozenset(
        pair for pair in v10_grants() if pair[0] is not Capability.RECORDS_ASSOCIATIONS_ASSERT
    )
    before = all_lineage_counts(runtime.engine)
    # The application service directly, with a remote Authorization: the façade
    # never publishes an ungranted name, so it would mask the handler's re-check.
    error = runtime.client_refused(_blocks(scene, "own-grant"), client=CHATLLM, grants=without)
    assert (error["code"], error.get("safe_details") or []) == ("unsupported", [])
    assert all_lineage_counts(runtime.engine) == before
    (facade,) = _run(
        _app(runtime.service, {"client": _context(without)}),
        [("client", _write("records.associations.assert", _payload(_blocks(scene, "own-grant"))))],
    )
    assert _refusal(facade) == ("unsupported", [])
    assert all_lineage_counts(runtime.engine) == before


# ---- the close gate --------------------------------------------------------------


def _try_close(runtime: S31Runtime, issue: str, key: str) -> dict[str, Any] | None:
    """`issues.close` by the local operator at the current version; the error, if any."""
    _, _, anchor = runtime.evidence_source(f"{key}-closure")
    version = runtime.issue_version(issue)
    envelope = runtime.invoke(close(issue, version, key, (anchor,)), surface=GATEWAY)
    error = envelope.to_canonical_dict().get("error")
    assert error is None or isinstance(error, dict)
    return error


def _held(error: dict[str, Any] | None) -> bool:
    return error is not None and (error["code"], error["safe_details"]) == (
        "conflict",
        ["closure_gate"],
    )


def _confirm_member(link: str, revision: int, key: str) -> ConfirmIssueMembership:
    return ConfirmIssueMembership(
        link_id=link,
        expected_revision=revision,
        idempotency_key=f"p1-confirm-member-{key}",
        reason="Checked.",
    )


def test_a_v10_client_fact_holds_the_close_until_a_cli_confirm(runtime: S31ReportRuntime) -> None:
    grants = v10_grants()
    # The live case: a v10 client's membership add holds the close until confirmed.
    live = _scene(runtime, "gate-live")
    (added,) = _run(
        _app(runtime.service, {"client": _context(grants)}),
        [
            (
                "client",
                _write(
                    "issues.memberships.add",
                    {
                        "issue_id": live["issue"],
                        "member": {"family": "task", "record_id": live["task"]},
                        "role": "reference",
                        "evidence_anchors": [],
                        "user_directed": True,
                    },
                ),
            )
        ],
    )
    live_member = _ok(added)["membership"]["link_id"]
    assert _held(_try_close(runtime, live["issue"], "gate-live-1"))
    runtime.ok(_confirm_member(live_member, 1, "gate-live"), surface=OperatorSurface.CLI)
    assert _try_close(runtime, live["issue"], "gate-live-2") is None
    # The ended case: a v10 client's end of a mandatory (open work) member leaves
    # an ended `client_identified` head, which still holds the close.
    scene = _scene(runtime, "gate-end")
    open_task = runtime.task("p1-gate-end-open")
    (work,) = _run(
        _app(runtime.service, {"client": _context(grants)}),
        [
            (
                "client",
                _write(
                    "issues.memberships.add",
                    {
                        "issue_id": scene["issue"],
                        "member": {"family": "task", "record_id": open_task},
                        "role": "work",
                        "evidence_anchors": [],
                    },
                ),
            )
        ],
    )
    member = _ok(work)["membership"]["link_id"]
    assert _held(_try_close(runtime, scene["issue"], "gate-end-1"))
    (ended,) = _run(
        _app(runtime.service, {"client": _context(grants)}),
        [
            (
                "client",
                _write(
                    "issues.memberships.end",
                    _payload(
                        EndIssueMembership(
                            link_id=member,
                            expected_revision=1,
                            idempotency_key="unused",
                            reason="A client ended the open work member.",
                        ),
                        user_directed=True,
                    ),
                ),
            )
        ],
    )
    assert _ok(ended)["membership"]["lifecycle_state"] == "ended"
    # The open work member is gone from the live set, yet the close is held.
    error = _try_close(runtime, scene["issue"], "gate-end-2")
    assert _held(error), error
    readiness = runtime.readiness(scene["issue"])
    assert readiness["ready"] is False
    assert [entry["link_id"] for entry in readiness["unreviewed_links"]] == [member]
    # Only the human channel clears it: the local operator's CLI confirm of the end.
    runtime.ok(_confirm_member(member, 2, "gate-end"), surface=OperatorSurface.CLI)
    assert _try_close(runtime, scene["issue"], "gate-end-3") is None
