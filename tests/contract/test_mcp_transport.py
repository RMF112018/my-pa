"""The MCP transport as a protocol, not as a function call.

`SPEC-AC-001`'s parity lives in `test_transport_parity.py`. What is here is the
part of the MCP adapter that has no counterpart in the other two transports and
that a parity matrix therefore cannot reach:

* the **handshake** — `initialize` answers, negotiates a protocol version, and
  declares a tools capability;
* the **tool list** — derived from the capability set rather than maintained, so
  a new capability appears without anyone editing the adapter, and the schema
  for a capability is derived from the command it builds;
* **stdio, in a real child process** — the transport `D-26` and `D-30` actually
  authorise, driven once end to end by the SDK's own client over pipes, because
  every other test here uses in-memory streams and would pass on a build whose
  stdio path was broken;
* **malformed input** — a bad tool name, arguments that are not a document, a
  payload past the ceiling — each a typed error rather than a protocol failure,
  a crash, or a stack trace.

The async boundary is asserted rather than described: `tools/call` runs the
synchronous application off the event loop, and a test that could not tell would
pass on a build that blocked it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Final

import apps.gateway as gateway
import pytest
from tests.conftest import (
    FakeProviders,
    Scene,
    World,
    build_service,
    operator,
    staged_record,
    staged_search,
)
from tests.contract.test_transport_parity import a_permitted_purpose, document, payloads_for
from tests.transports import McpTransport, mcp_transport

import my_pa.adapters.mcp.server as mcp_module
from my_pa.adapters.mcp import TOOLS, create_mcp_server
from my_pa.adapters.mcp.tools import payload_schema_for
from my_pa.adapters.normalization import MAX_REQUEST_BYTES, PAYLOAD_KEY
from my_pa.application.commands import Command
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability

MCP_SOURCE = Path(mcp_module.__file__).read_text(encoding="utf-8")

#: What the `served` fixture hands a test: a session that has not been entered
#: yet, so a test that wants two of them can have two.
type Served = AbstractContextManager[McpTransport]


@pytest.fixture
def served(scene: Scene) -> Served[McpTransport]:
    """One running MCP server and an initialized client over it."""
    staged_record(scene, text="quarterly revenue review")
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    return mcp_transport(build_service(scene.world, scene.providers), scene.principal)


# ---- the handshake -----------------------------------------------------------


def test_initialize_answers_with_this_build(served: Served[McpTransport], scene: Scene) -> None:
    """`initialize` is the SDK's, and what it announces is this package's."""
    with served as session:
        result = session.initialize_result()
    assert result.server_info.name == mcp_module.SERVER_NAME
    assert result.server_info.version == "0.1.0"
    assert result.protocol_version, "no protocol version was negotiated"
    assert result.capabilities.tools is not None, "the server declares no tools capability"


def test_the_server_name_is_neutral() -> None:
    """`AGENTS.md` section 4: an MCP capability name carries no former-employer branding."""
    names = [mcp_module.SERVER_NAME, *(tool.name for tool in TOOLS)]
    for name in names:
        assert name == name.lower()
        assert not {"hb", "hbintel", "hedrick"} & set(name.replace(".", " ").split())


# ---- the tool list, derived --------------------------------------------------


def test_tools_list_publishes_exactly_the_capability_set(served: Served[McpTransport]) -> None:
    """Over the protocol, not off the constant: what a client actually receives."""
    with served as session:
        listed = session.list_tools()
    assert [tool.name for tool in listed.tools] == [c.value for c in Capability]
    assert all(tool.description for tool in listed.tools), "a tool has no description"


def test_no_capability_name_is_written_down_in_the_adapter() -> None:
    """The list is derived, and this is what makes "derived" checkable.

    Equality with `Capability` above is also satisfied by the same names typed
    out by hand that happen to match today. What rules that out is that none of
    the capability strings appears in the adapter's source at all — so a new
    capability cannot be missing from a list nobody wrote.
    """
    adapters = Path(mcp_module.__file__).resolve().parent
    for path in sorted(adapters.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        named = sorted(c.value for c in Capability if f'"{c.value}"' in text)
        assert not named, f"{path.name} writes the capability names {named} down"


def test_a_ninth_capability_gets_a_schema_without_the_adapter_being_edited() -> None:
    """The derivation is generic, shown against a command that does not exist.

    A synthetic thirteenth command is put through the same schema builder the
    twelve go through. If the builder were a lookup table it would have nothing to say
    about this one; because it reads the dataclass, it describes it exactly.
    """
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class NinthCommand:
        """`ninth.capability`: a command this build does not have."""

        subject_id: str
        tags: tuple[str, ...]
        limit: int | None = None
        verbose: bool = False

    schema = payload_schema_for(NinthCommand)
    assert schema["properties"] == {
        "subject_id": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "limit": {"type": "integer"},
        "verbose": {"type": "boolean"},
    }
    assert schema["required"] == ["subject_id", "tags"]


def test_every_command_field_has_a_described_json_type() -> None:
    """No published schema silently says "anything" about a field that has a type.

    The builder answers `{}` for a shape it does not describe, which is honest
    at run time and would be a slow erosion if it became normal. This is what
    keeps it from becoming normal.
    """
    for command in Command.__value__.__args__:
        schema = payload_schema_for(command)
        undescribed = sorted(name for name, value in schema["properties"].items() if not value)
        assert not undescribed, f"{command.__name__} publishes {undescribed} as unconstrained"


def test_a_tool_schema_is_the_document_normalize_reads() -> None:
    """The published schema and the accepted document are the same shape.

    A schema that advertised fields `normalize` rejects, or omitted ones it
    requires, would be a client's only description of a request being wrong.
    `capability` is the one deliberate removal: the tool name carries it, and a
    document that names it again is refused.
    """
    for capability, tool in zip(Capability, TOOLS, strict=True):
        properties = set(tool.input_schema["properties"])
        assert "capability" not in properties
        assert properties == (set(RequestMetadata.model_fields) - {"capability"}) | {PAYLOAD_KEY}
        assert tool.input_schema["additionalProperties"] is False
        assert tool.name == capability.value


def test_a_pruned_definition_is_not_left_dangling() -> None:
    """Removing `capability` must remove its definition too, or the schema lies."""
    for tool in TOOLS:
        rendered = json.dumps(tool.input_schema)
        assert "Capability" not in rendered, "the removed field's definition survived"
        for name in tool.input_schema.get("$defs", {}):
            assert f'"#/$defs/{name}"' in rendered, f"{name} is defined and referenced by nothing"


def test_the_schema_builder_would_notice_an_undescribed_type() -> None:
    """Guard the rule above: a builder that described everything proves nothing."""
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Odd:
        """A field shape nothing here describes."""

        mapping: dict[str, int]

    assert payload_schema_for(Odd)["properties"] == {"mapping": {}}


def test_a_command_may_publish_nested_object_item_shape() -> None:
    """Unconstrained dict tuples can still publish the item contract they enforce."""
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Nested:
        items: tuple[dict[str, object], ...]

    Nested.mcp_payload_properties = {  # type: ignore[attr-defined]
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"kind": {"type": "string"}},
                "required": ["kind"],
            },
        }
    }
    items = payload_schema_for(Nested)["properties"]["items"]
    assert items["items"]["properties"]["kind"] == {"type": "string"}
    assert items["items"]["required"] == ["kind"]


def test_a_command_may_publish_payload_schema_applicators() -> None:
    """Variant discrimination lives on the payload object, not as invented fields."""
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Nested:
        schema_version: str
        items: tuple[dict[str, object], ...]

    Nested.mcp_payload_properties = {  # type: ignore[attr-defined]
        "items": {"type": "array", "items": {"type": "object"}},
        "if": {
            "properties": {"schema_version": {"const": "v1"}},
            "required": ["schema_version"],
        },
        "then": {"properties": {"items": {"maxItems": 1}}},
    }
    schema = payload_schema_for(Nested)
    assert schema["if"]["properties"]["schema_version"] == {"const": "v1"}
    assert schema["then"]["properties"]["items"]["maxItems"] == 1
    assert "if" not in schema["properties"]
    assert "then" not in schema["properties"]


# ---- tools/call --------------------------------------------------------------


def test_a_call_returns_the_envelope_bytes_and_not_a_reassembled_shape(
    served: Served[McpTransport],
    scene: Scene,
) -> None:
    """One content block, the envelope's own canonical JSON, `isError` from the answer."""
    with served as session:
        result = session.call(
            Capability.CAPABILITIES_GET.value,
            document(Capability.CAPABILITIES_GET, scene.principal.principal_id, {}),
        )
    assert result.is_error is False
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    envelope = json.loads(result.content[0].text)
    assert envelope["error"] is None
    assert envelope["disclosure"] is not None


def test_a_refusal_sets_is_error(served: Served[McpTransport], scene: Scene) -> None:
    """The protocol's failure flag is a function of the envelope, not a second judgement."""
    with served as session:
        result = session.call(
            Capability.SOURCES_LIST.value,
            document(
                Capability.SOURCES_LIST,
                scene.principal.principal_id,
                {"source_id": "not-an-identifier"},
            ),
        )
    assert result.is_error is True
    body = json.loads(result.content[0].text)
    assert (body.get("error") or body)["code"] == ErrorCode.INVALID_REQUEST.value


#: Every way a tool call can arrive malformed, and what each is. Each is a typed
#: error rather than a protocol failure: the connection survives and the client
#: gets an answer it can read.
MALFORMED = [
    ("a tool that does not exist", "sources.destroy", {}),
    ("a tool name that is empty", "", {}),
    ("a tool name that is a capability prefix", "sources", {}),
    ("no arguments at all", Capability.SOURCES_LIST.value, None),
    ("arguments that are not a document", Capability.SOURCES_LIST.value, {"payload": []}),
    ("a payload field that does not exist", Capability.SOURCES_LIST.value, None),
]


@pytest.mark.parametrize(("name", "tool", "arguments"), MALFORMED, ids=lambda value: str(value))
def test_malformed_input_is_a_typed_error(
    name: str,
    tool: str,
    arguments: dict[str, Any] | None,
    served: Served[McpTransport],
    scene: Scene,
) -> None:
    """Never a stack trace, never an unhandled exception, always a code."""
    if name == "a payload field that does not exist":
        arguments = document(
            Capability.SOURCES_LIST,
            scene.principal.principal_id,
            {"source_id": scene.source.source_id, "not_a_field": 1},
        )
    with served as session:
        result = session.call(tool, arguments)
        # The connection is still usable, which is the half a single call
        # cannot show: a handler that took the server down would answer the
        # first request and none after it.
        after = session.call(
            Capability.CAPABILITIES_GET.value,
            document(Capability.CAPABILITIES_GET, scene.principal.principal_id, {}),
        )
    assert result.is_error is True, name
    body = json.loads(result.content[0].text)
    code = (body.get("error") or body)["code"]
    assert code == ErrorCode.INVALID_REQUEST.value, name
    assert "Traceback" not in result.content[0].text
    assert after.is_error is False, f"the connection did not survive {name}"


def test_a_payload_past_the_ceiling_is_refused(served: Served[McpTransport], scene: Scene) -> None:
    """The bound is the HTTP transport's own, so three transports enforce one number."""
    oversized = document(
        Capability.SOURCES_LIST,
        scene.principal.principal_id,
        {"source_id": scene.source.source_id, "filler": "x" * (MAX_REQUEST_BYTES + 1)},
    )
    with served as session:
        result = session.call(Capability.SOURCES_LIST.value, oversized)
    assert result.is_error is True
    body = json.loads(result.content[0].text)
    assert (body.get("error") or body)["code"] == ErrorCode.INVALID_REQUEST.value
    assert "x" * 64 not in result.content[0].text, "the oversized payload was echoed"


def test_the_ceiling_admits_the_largest_request_the_contract_allows(
    served: Served[McpTransport],
    scene: Scene,
) -> None:
    """Guard the bound: one set below a real request would refuse legitimate work."""
    enrollment = document(
        Capability.SOURCES_ENROLL,
        scene.principal.principal_id,
        payloads_for(scene, staged_record(scene, text="x"))[Capability.SOURCES_ENROLL],
    )
    assert len(json.dumps(enrollment).encode()) < MAX_REQUEST_BYTES
    with served as session:
        result = session.call(Capability.SOURCES_ENROLL.value, enrollment)
    assert result.is_error is False, result.content[0].text


# ---- the async boundary ------------------------------------------------------


def test_the_application_runs_off_the_event_loop(scene: Scene) -> None:
    """`D-27`: the synchronous application does not run on the loop thread.

    Measured rather than described. The service records the thread it was
    invoked on; a handler that called it directly would record the loop's own
    thread, and every other test in this file would still pass while one slow
    request stalled every other request on the connection.
    """
    threads: list[str] = []
    service = build_service(scene.world, scene.providers)
    invoke = service.invoke

    def watched(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - a pass-through
        threads.append(threading.current_thread().name)
        return invoke(*args, **kwargs)

    object.__setattr__(service, "invoke", watched)
    with mcp_transport(service, scene.principal) as session:
        session.call(
            Capability.CAPABILITIES_GET.value,
            document(Capability.CAPABILITIES_GET, scene.principal.principal_id, {}),
        )
    assert threads, "the application was never invoked"
    assert threads[0] != "mcp-under-test", f"the application ran on the loop thread: {threads}"


# ---- stdio, in a real child process ------------------------------------------


def _framed(message: dict[str, Any]) -> bytes:
    return (json.dumps(message) + "\n").encode()


def _child_tool_list(**settings: str) -> tuple[list[str], bytes]:
    """Spawn `apps/gateway.py mcp`, handshake, `tools/list`, and return the names.

    Factored out because WP-28 gave the surface two composition-time switches,
    and the only honest way to test a switch that is read at startup is to start
    the process with it set. Everything about the child is the same in each
    case except the environment, so the differences below are the settings and
    nothing else.
    """
    environment = {
        **os.environ,
        "PYTHONPATH": (
            f"{Path(gateway.__file__).resolve().parents[1] / 'src'}:"
            f"{Path(gateway.__file__).resolve().parents[1]}"
        ),
        "MY_PA_DATABASE_URL": "postgresql+psycopg://someone@127.0.0.1:1/nothing",
        **settings,
    }
    process = subprocess.Popen(  # noqa: S603 - fixed argument list, no shell
        [sys.executable, str(Path(gateway.__file__)), "mcp"],
        cwd=Path(gateway.__file__).resolve().parents[1],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(
            _framed(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"},
                    },
                }
            )
        )
        process.stdin.flush()
        first = process.stdout.readline()
        process.stdin.write(_framed({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        process.stdin.write(_framed({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
        process.stdin.flush()
        second = process.stdout.readline()
    finally:
        process.terminate()
        try:
            _, errors = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover - a failure path
            process.kill()
            _, errors = process.communicate(timeout=30)

    handshake = json.loads(first)
    assert handshake["id"] == 1, first
    assert handshake["result"]["serverInfo"]["name"] == mcp_module.SERVER_NAME
    listed = json.loads(second)
    assert listed["id"] == 2
    return [tool["name"] for tool in listed["result"]["tools"]], errors


#: The capabilities a process must be *composed* for, rather than merely
#: built with. Derived from the enum rather than written out, so another joins
#: without editing this file — and asserted non-empty below, because an empty set
#: would make both halves of the claim vacuous.
#:
#: Two families now. `documents.` needs a managed byte store. `entities.` needs
#: the relationship plane switched on, and that switch is the whole of
#: `D-RI-01`: `adapters.mcp.remote` derives the remote tool profile from the
#: capability set with no per-capability exclusion list, so "this build serves
#: it" and "a remote client can reach it" are one decision. This test is where
#: that decision is proved — against a real child process, in the transport an
#: operator actually runs, rather than against a code path.
_COMPOSED_PREFIXES: Final = ("documents.", "entities.")

_COMPOSED_CAPABILITIES: Final = frozenset(
    capability for capability in Capability if capability.value.startswith(_COMPOSED_PREFIXES)
)


def test_a_real_child_process_publishes_only_what_it_was_composed_with() -> None:
    """What `tools/list` publishes is what the process can serve, in a real child.

    **Two children, and the difference between them is one environment
    variable.**

    * *Unconfigured* — no `MY_PA_MANAGED_DOCUMENT_ROOT`, so no byte store is
      composed and the `documents.` names are withheld. This is the state every
      process this build has run in; what WP-28 changed is that capabilities now
      exist which a process can lack the composition for, so "the tool list is
      the capability set" stopped being true and "the tool list is what this
      process can serve" took its place.
    * *Kill switch engaged* — nothing at all, in the transport an operator
      actually runs rather than in an in-memory session. A switch proved only
      against a memory stream would be a switch proved about a code path rather
      than about a process.

    Both children keep the unreachable database URL this module uses
    deliberately: neither composition reads a row. The *third* case — a process
    with a managed root, publishing all sixty-two — does read one, because the
    store is constructed with the configured source roots to refuse an
    overlapping root, so it is proved in
    `test_a_child_with_a_managed_root_publishes_every_capability` against a real
    server instead.
    """
    assert _COMPOSED_CAPABILITIES, "no capability needs composition, so this proves nothing"

    unconfigured, _errors = _child_tool_list()
    assert unconfigured == [
        capability.value for capability in Capability if capability not in _COMPOSED_CAPABILITIES
    ]
    assert not any(name.startswith("documents.") for name in unconfigured)

    killed, _errors = _child_tool_list(MY_PA_MCP_SURFACE_DISABLED="true")
    assert killed == [], "the kill switch left tools published in a real child process"


@pytest.mark.database
def test_a_child_with_a_managed_root_publishes_every_capability(tmp_path: Path) -> None:
    """The other half: composed for the managed plane, the child publishes all of it.

    Marked `database` because composing the byte store reads the configured
    source roots — the check that refuses a managed root which is, contains, or
    lies inside one — so a process with a managed root and no database refuses to
    start rather than composing a store that compared against nothing. That is
    the fail-closed direction and it is the reason this case cannot join the two
    above.

    The managed root is a `tmp_path` directory removed with the test. Nothing is
    written into it: no request is made, only a handshake and a listing.
    """
    root = tmp_path / "managed"
    root.mkdir()
    composed, _errors = _child_tool_list(
        MY_PA_DATABASE_URL=os.environ["MY_PA_DATABASE_URL"],
        MY_PA_MANAGED_DOCUMENT_ROOT=str(root),
        MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED="true",
    )
    assert composed == [capability.value for capability in Capability]
    assert {capability.value for capability in _COMPOSED_CAPABILITIES} <= set(composed)
    assert not any(root.iterdir()), "a listing wrote into the managed root"


def test_the_stdio_transport_serves_a_real_child_process() -> None:
    """`D-26` and `D-30`: the transport an operator actually runs, over pipes.

    The composition root is started as a child, spoken to in JSON-RPC on its
    standard input, and read back from its standard output. Two things this
    proves that no in-memory session can: the stdio framing works in a process
    that owns real file descriptors, and **the startup notice is not on the
    wire** — a single line printed to standard output would be a parse failure
    on the client's first read, and the whole reason `_mcp` prints to standard
    error.

    It spawns an interpreter and is measured at under half a second, and it is
    deliberately **not** marked `slow`: the only CI selections are FAST and the
    database tier, so a `slow` mark on the one test that exercises the
    authorised transport would mean the authorised transport is never exercised
    in CI at all. The database URL is deliberately unreachable — composition is
    lazy and the handshake needs no connection, so nothing here depends on a
    server, and a URL that resolved would make this test depend on one.
    """
    environment = {
        **os.environ,
        "PYTHONPATH": (
            f"{Path(gateway.__file__).resolve().parents[1] / 'src'}:"
            f"{Path(gateway.__file__).resolve().parents[1]}"
        ),
        "MY_PA_DATABASE_URL": "postgresql+psycopg://someone@127.0.0.1:1/nothing",
    }
    process = subprocess.Popen(  # noqa: S603 - fixed argument list, no shell
        [sys.executable, str(Path(gateway.__file__)), "mcp"],
        cwd=Path(gateway.__file__).resolve().parents[1],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(
            _framed(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"},
                    },
                }
            )
        )
        process.stdin.flush()
        first = process.stdout.readline()
        process.stdin.write(_framed({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        process.stdin.write(_framed({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
        process.stdin.flush()
        second = process.stdout.readline()
    finally:
        process.terminate()
        try:
            _, errors = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover - a failure path
            process.kill()
            _, errors = process.communicate(timeout=30)

    handshake = json.loads(first)
    assert handshake["id"] == 1, first
    assert handshake["result"]["serverInfo"]["name"] == mcp_module.SERVER_NAME
    listed = json.loads(second)
    assert listed["id"] == 2
    # *What* the list contains is the composition claim above, because it depends
    # on how the child was composed. What matters here is that a list came back
    # at all over real pipes: the framing worked and the stream was not
    # corrupted.
    assert listed["result"]["tools"], "the child published no tool at all"
    # And the operator's notice was on standard error, where it cannot corrupt
    # the stream the client is parsing.
    assert b"serving     mcp on stdio" in errors
    # Pinned to the whole sentence, not a fragment of it. The notice is printed
    # unconditionally and reads no store, so the only thing keeping it true is
    # that it states a condition instead of asserting an absence; a substring
    # match would have passed against the superseded wording, which asserted
    # that no source provider was configured at all.
    assert (
        b"notice      sources.list, sources.metadata and sources.fetch answer 'unavailable' "
        b"for every source no operator has registered; registration names the source's root "
        b"by exact path, and this process configures none"
    ) in errors


def test_the_composition_root_offers_no_network_option() -> None:
    """`D-30`: there is no host, no port, and no credential on the MCP path."""
    parser = gateway.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["mcp", "--host", "0.0.0.0"])  # noqa: S104 - the value being refused
    parsed = parser.parse_args(["mcp"])
    assert parsed.command == "mcp"
    assert not hasattr(parsed, "port")


def test_the_server_is_composed_with_the_principal_it_is_given() -> None:
    """The transport chooses no principal; it is handed one, like the other two."""
    server = create_mcp_server(build_service(World(), FakeProviders({})), principal=operator())
    assert server.name == mcp_module.SERVER_NAME
    assert server.get_request_handler("tools/call") is not None
    assert server.get_request_handler("tools/list") is not None
    # And the surfaces `D-30` refuses are not registered.
    assert server.get_request_handler("resources/list") is None
    assert server.get_request_handler("prompts/list") is None


def test_a_permitted_purpose_exists_for_every_capability() -> None:
    """Guard the fixtures above: a capability with no permitted purpose is untestable."""
    assert {a_permitted_purpose(c) for c in Capability}
