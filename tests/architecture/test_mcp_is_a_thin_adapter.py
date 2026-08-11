"""`adapters/mcp` re-implements nothing, and the claim is a parse rather than a grep.

Operating-brief section 25 and WP-28's first acceptance criterion: *Frontier MCP
is a thin adapter over canonical application services; do not create a separate
business-logic implementation inside MCP.* "No parallel business logic" is not a
statement anyone can check by reading, because the way it fails is a helper added
to a transport module six months from now that happens to open a connection, or
compare a Principal, or decide that a version number is stale. So it is four
structural claims here instead:

1. **The universe is closed and counted.** Every `.py` file under
   `src/my_pa/adapters/mcp/` is read, the enumeration is compared against a fresh
   `rglob`, and the count is pinned. WP-23's no-vector guard missed an entire file
   type; WP-27's write guard missed one `.py` under `docs/`. A guard that does not
   say what it looked at has not said anything.
2. **Imports are an allowlist, not a denylist.** A denylist forbids only the
   spellings its author imagined — WP-18 bought that lesson with `CNSaveRequest`.
   The set of modules this package may import is written out exactly; a new one
   is a decision recorded here, and `sqlalchemy`, `my_pa.infrastructure`,
   `my_pa.application.managed_documents`, `my_pa.application.authorization` and
   `my_pa.domain.policy` are outside it because each is a piece of the
   implementation the adapter must reach *through* `invoke` rather than beside it.
3. **Forbidden operations are matched on the AST**, in the call form, the
   attribute form and the unapplied form, so `authorize`, `sink.record`,
   `repository.admit`, `store.put`, `connection.execute`, `.commit()` and the
   domain's own state transitions redden however they are spelled.
4. **Every dispatch path terminates in `normalize` + one `invoke`.** There is
   exactly one call to each in the whole package, both inside `_answer`, and
   `_call_tool` reaches the application only by handing `_answer` to an executor.
   A second `invoke` anywhere is a second pipeline.

And two claims that belong to the same file because they are about the same
surface:

5. **No published tool takes a location.** The tool input schemas are *derived*
   from the command dataclasses, so a field added to a command is a new wire
   parameter — which is exactly how a path would get back onto a surface WP-27
   made structurally pathless. Every property name of every published schema is
   checked against a location vocabulary, and the payload half is checked for
   `principal_id`.
6. **No network transport is importable from this package.** `D-26`/`D-30` make
   the surface stdio-only; the SDK ships SSE, streamable-HTTP and WebSocket
   servers in the same distribution, and importing one is all it would take.

Nothing here opens a connection, reaches a source, or touches a database.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from my_pa.adapters.mcp.tools import TOOLS

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa" / "adapters" / "mcp"

#: Every module in the package, by name. Written out so that a new module is a
#: decision recorded here rather than a file that quietly joins the scan — or,
#: worse, one the scan never notices it did not read.
MODULES: Final[frozenset[str]] = frozenset({"__init__.py", "server.py", "tools.py"})

#: Exactly what this package may import from this repository. An allowlist, in
#: the `D-81` shape: an entry that no longer matches reddens, and a new import is
#: a decision written here beside the reason it is admissible.
#:
#: What each one is, and why reaching it is not reaching an implementation:
#:
#: * `adapters.normalization` — the one shared `(metadata, command)` builder all
#:   three transports call. Reaching it is the *point*; a transport that did not
#:   would be building its own request pair.
#: * `adapters.mcp.tools` — this package's own module.
#: * `application.commands` — the command *types*, read to derive schemas. Types,
#:   not behaviour: `tools.py` never constructs one.
#: * `application.errors` — the public error vocabulary and `problem_detail`, so
#:   a refusal this transport makes is rendered the way the application renders
#:   its own instead of inventing a second error body.
#: * `application.service` — `ApplicationService`, for the type of the object it
#:   is handed and for the one `invoke` it calls.
#: * `contracts.v1.envelope` / `contracts.v1.errors` — the published shapes.
#: * `domain.common.identifiers` / `domain.source.registry` — `IdKind` and
#:   `issue_identifier`, to mint the correlation identifier a refusal that never
#:   reached the application must still carry.
#: * `domain.identity.operation` — the `Capability` enum, read to name tools.
#: * `domain.identity.principal` — the `Principal` type it is handed.
#: * `my_pa` — `__version__`, published in `initialize`.
ADMISSIBLE_IMPORTS: Final[frozenset[str]] = frozenset(
    {
        "my_pa",
        "my_pa.adapters.mcp.server",
        "my_pa.adapters.mcp.tools",
        "my_pa.adapters.normalization",
        "my_pa.application.commands",
        "my_pa.application.errors",
        "my_pa.application.service",
        "my_pa.contracts.v1.envelope",
        "my_pa.contracts.v1.errors",
        "my_pa.domain.common.identifiers",
        "my_pa.domain.identity.operation",
        "my_pa.domain.identity.principal",
        "my_pa.domain.source.registry",
    }
)

#: The third-party and standard-library modules this package may import. Held to
#: the same exactness for the reason claim 6 exists: the SDK's network servers
#: live in the same distribution as its stdio one, so "the SDK is admissible" is
#: not a safe grain to reason at.
ADMISSIBLE_FOREIGN_IMPORTS: Final[frozenset[str]] = frozenset(
    {
        "__future__",
        "asyncio",
        "collections.abc",
        "dataclasses",
        "datetime",
        "enum",
        "json",
        "mcp.server.context",
        "mcp.server.lowlevel",
        "mcp.server.stdio",
        "mcp.types",
        "types",
        "typing",
    }
)

#: Names this package may not call, in any spelling the AST can see.
#:
#: Each is a piece of the implementation the adapter must reach *through*
#: `ApplicationService.invoke` and never beside it: the authorization decision,
#: the audit write, the managed-document repository's own write path, the byte
#: store, a transaction, a raw statement, and the two domain state transitions
#: the managed plane has. `accept` is here because WP-11's open NOTE 2 concerns
#: it and a transport calling it would be a governed write with no review behind
#: it at all.
FORBIDDEN_CALLS: Final[frozenset[str]] = frozenset(
    {
        "accept",
        "admit",
        "authorize",
        "commit",
        "connect",
        "create_engine",
        "evaluate",
        "execute",
        "record",
        "replay_for",
        "restore_version",
        "rollback",
        "transition",
    }
)

#: Attribute chains this package may not reach through, whatever the receiver is
#: called. `.put(` on a byte store and `.audit` on a unit of work are the two a
#: reimplementation would most naturally use, and neither has a call name the set
#: above would catch on its own.
FORBIDDEN_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        "audit",
        "captures",
        "enrollments",
        "knowledge",
        "managed_documents",
        "put",
        "put_manifest",
        "reviews",
        "sources",
        "unit_of_work",
    }
)

#: Property names that would put a location on the wire. Matched as substrings of
#: a lowercased property name, so `target_path`, `filename` and `rootDir` are all
#: caught; the vocabulary is deliberately wider than the shapes that exist.
LOCATION_WORDS: Final[tuple[str, ...]] = (
    "path",
    "file",
    "dir",
    "folder",
    "root",
    "location",
    "uri",
    "url",
    "shard",
    "destination",
    "target",
    "prefix",
    "volume",
    "mount",
    "share",
    "unc",
    "drive",
)

#: The SDK's other transports, the servers that would host one, and the standard
#: library's own network doors. Named exactly rather than matched by prefix,
#: because "anything under `mcp.server`" would also forbid the stdio server this
#: package is built on.
NETWORK_MODULES: Final[frozenset[str]] = frozenset(
    {
        "aiohttp",
        "http",
        "http.client",
        "http.server",
        "httpx",
        "mcp.client.sse",
        "mcp.client.streamable_http",
        "mcp.client.websocket",
        "mcp.server.sse",
        "mcp.server.streamable_http",
        "mcp.server.websocket",
        "requests",
        "socket",
        "socketserver",
        "ssl",
        "starlette",
        "urllib",
        "urllib.request",
        "uvicorn",
        "websockets",
    }
)


#: The one property the vocabulary above matches that is **not** a location, with
#: the reason it is not — an exemption list of exactly one, in the `D-81` shape,
#: so a second one is a decision somebody writes down beside this sentence.
#:
#: `sources.enroll`'s `root_object_id` is an opaque `obj_…` source-object
#: identifier: it names a node in a source's own object graph, is minted by this
#: product, and is resolved by the provider through `knowledge.source_objects`.
#: It is matched only because "root" is in the vocabulary, and "root" stays in
#: the vocabulary because it is the word `managed_root` and `native_root` are
#: spelled with — removing it to silence this one entry would blind the scan to
#: the two names that would actually matter.
EXEMPT_PROPERTIES: Final[frozenset[tuple[str, str]]] = frozenset(
    {("sources.enroll", "root_object_id")}
)


def _modules() -> tuple[Path, ...]:
    """Every Python file in the package, as a sorted tuple."""
    return tuple(sorted(path for path in PACKAGE.rglob("*.py") if "__pycache__" not in path.parts))


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_modules(tree: ast.AST) -> set[str]:
    """Every module name an `import` or `from … import` in `tree` names.

    `ImportFrom` with `level > 0` is a relative import and is reported as the
    literal dots plus the module, so a relative import cannot slip past a scan
    that only compares absolute names — there are none in this package today and
    this is what keeps that true.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
    return found


def called_names(tree: ast.AST) -> list[tuple[int, str]]:
    """Every name a `Call` in `tree` invokes, as `(line, name)`.

    The *called* name only — `a.b.c()` reports `c` — because what is forbidden is
    performing the operation, however the receiver was obtained. A method
    referenced without being called is caught by `referenced_attributes` below,
    which is the shape WP-17's guard was corrected into after an unapplied
    `CNContactStore.execute` got through.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            found.append((node.lineno, node.func.id))
        elif isinstance(node.func, ast.Attribute):
            found.append((node.lineno, node.func.attr))
    return found


def referenced_attributes(tree: ast.AST) -> list[tuple[int, str]]:
    """Every attribute name read anywhere in `tree`, applied or not."""
    return [(node.lineno, node.attr) for node in ast.walk(tree) if isinstance(node, ast.Attribute)]


def _schema_property_names(schema: object) -> Iterator[str]:
    """Every property name anywhere in a JSON Schema document, at any depth.

    Recursive rather than one level deep: a nested object, an array's `items`, and
    a `$defs` entry are all places a property can be declared, and a scan that
    read only the top level would be satisfied by any of them.
    """
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                yield from (str(name) for name in value)
            yield from _schema_property_names(value)
    elif isinstance(schema, list):
        for entry in schema:
            yield from _schema_property_names(entry)


# ---- claim 1: the universe --------------------------------------------------


def test_the_scan_reads_every_module_in_the_package() -> None:
    """Guards every zero below. A walk that parsed nothing passes everything."""
    modules = _modules()
    assert {path.name for path in modules} == MODULES
    assert len(modules) == 3, f"the package now holds {[p.name for p in modules]}"
    # A positive control on the parser: the package really does contain code, so
    # the AST claims below are about statements rather than about empty files.
    statements = sum(len(list(ast.walk(_tree(path)))) for path in modules)
    assert statements > 500, f"only {statements} AST nodes were parsed"


# ---- claim 2: imports are an allowlist --------------------------------------


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_the_package_imports_only_what_is_registered(path: Path) -> None:
    """A closed set, so a new reach is a decision and not a diff."""
    imported = imported_modules(_tree(path))
    admissible = ADMISSIBLE_IMPORTS | ADMISSIBLE_FOREIGN_IMPORTS
    unregistered = sorted(imported - admissible)
    assert not unregistered, (
        f"{_relative(path)} imports {unregistered}, which is not in this file's "
        "allowlist. `adapters/mcp` is a thin adapter over `ApplicationService.invoke` "
        "(operating-brief section 25): reaching persistence, a repository, the "
        "authorization path or the managed-document service directly is the "
        "parallel implementation that criterion forbids"
    )


def test_the_allowlist_is_not_a_superset_of_a_dead_tree() -> None:
    """The `D-81` half: a stale entry reddens rather than sitting there.

    An allowlist that admitted modules nothing imports would grow into a list of
    permissions rather than a description, and the next reader could not tell
    which entries were load-bearing.
    """
    imported: set[str] = set()
    for path in _modules():
        imported |= imported_modules(_tree(path))
    unused = sorted(ADMISSIBLE_IMPORTS - imported)
    assert not unused, f"the repository allowlist admits {unused}, which nothing imports"


# ---- claim 3: forbidden operations ------------------------------------------


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_the_package_performs_no_forbidden_operation(path: Path) -> None:
    """Authorization, audit, persistence, idempotency and state transitions."""
    tree = _tree(path)
    calls = [(line, name) for line, name in called_names(tree) if name in FORBIDDEN_CALLS]
    assert not calls, (
        f"{_relative(path)} calls {calls}. Every one of these belongs behind "
        "`ApplicationService.invoke`; a transport performing one is performing "
        "business logic beside the application rather than through it"
    )
    attributes = [
        (line, name) for line, name in referenced_attributes(tree) if name in FORBIDDEN_ATTRIBUTES
    ]
    assert not attributes, (
        f"{_relative(path)} reaches {attributes}. A repository, a byte store or a "
        "unit of work reached from a transport is the parallel implementation "
        "operating-brief section 25 forbids"
    )


def test_the_forbidden_sets_are_not_empty() -> None:
    """`D-55`: a control that forbids nothing distinguishes nothing."""
    assert len(FORBIDDEN_CALLS) == 13
    assert len(FORBIDDEN_ATTRIBUTES) == 10
    # And the names are real: each appears somewhere in the tree this package is
    # forbidden to reach, so the sets are a description of the implementation
    # rather than a list of words. `src/my_pa` rather than `application` alone,
    # because some of them are infrastructure's — `create_engine` and `connect`
    # are exactly the two a transport would use to build a second pipeline, and
    # neither could appear in `application`, which may not import `sqlalchemy`.
    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "my_pa").rglob("*.py")
        if "__pycache__" not in path.parts and "adapters/mcp" not in path.as_posix()
    )
    missing = sorted(name for name in FORBIDDEN_CALLS | FORBIDDEN_ATTRIBUTES if name not in corpus)
    assert not missing, f"{missing} name nothing in `src/my_pa`, so forbidding them is theatre"


# ---- claim 4: every path terminates in normalize + one invoke ---------------


def test_there_is_exactly_one_normalize_and_one_invoke_in_the_package() -> None:
    """The termination claim, as two counts and a location.

    A second `invoke` is a second pipeline, and a `normalize` that is not paired
    with one is a transport building a request it then does something else with.
    Both live in `_answer`, which is what `_call_tool` hands to the executor.
    """
    sites: dict[str, list[tuple[str, int]]] = {"normalize": [], "invoke": []}
    for path in _modules():
        for line, name in called_names(_tree(path)):
            if name in sites:
                sites[name].append((_relative(path), line))
    assert len(sites["normalize"]) == 1, sites["normalize"]
    assert len(sites["invoke"]) == 1, sites["invoke"]
    assert sites["normalize"][0][0] == "src/my_pa/adapters/mcp/server.py"
    assert sites["invoke"][0][0] == "src/my_pa/adapters/mcp/server.py"

    answer = _function(_tree(PACKAGE / "server.py"), "_answer")
    inside = {name for _, name in called_names(answer)}
    assert {"normalize", "invoke"} <= inside, "`_answer` no longer builds and dispatches a request"


def test_the_tool_handler_reaches_the_application_only_through_the_answer() -> None:
    """`_call_tool` hands `_answer` to an executor and calls nothing else that acts.

    The names it may call are written out. `run_in_executor` is how the
    synchronous application is reached from the async edge; the rest build the
    protocol result. A handler that called the service directly, or called a new
    helper that did, is a second path and reddens here.
    """
    handler = _function(_tree(PACKAGE / "server.py"), "_call_tool")
    called = sorted({name for _, name in called_names(handler)})
    assert called == [
        "CallToolResult",
        "TextContent",
        "UnsupportedError",
        "_problem",
        "get_running_loop",
        "run_in_executor",
        "to_canonical_json",
    ], called
    # `UnsupportedError` and `_problem` are the kill switch's refusal, built from
    # the application's own error vocabulary rather than as a second error body,
    # and `to_canonical_json` renders it. None of the three reaches the service:
    # the disabled branch returns before the executor is touched.
    # `_answer` is passed, not called, so it appears as a `Name` load rather than
    # in the call list. It must still be the function handed over.
    names = {node.id for node in ast.walk(handler) if isinstance(node, ast.Name)}
    assert "_answer" in names


def _function(tree: ast.AST, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined in the module scanned")


# ---- claim 5: no published tool takes a location ---------------------------


def test_no_published_tool_schema_names_a_location() -> None:
    """WP-27 made containment structural by removing the path parameter. This keeps it.

    The tool schemas are derived from the command dataclasses, so a field added
    to a command becomes a wire parameter without anyone editing a schema — which
    is precisely how a location would reappear on a surface that has none. Every
    property name at every depth of every published schema is checked.
    """
    assert TOOLS, "no tool is published, so this rule is describing nothing"
    offending: list[tuple[str, str]] = []
    for tool in TOOLS:
        for name in _schema_property_names(tool.input_schema):
            lowered = name.lower()
            if (tool.name, name) in EXEMPT_PROPERTIES:
                continue
            if any(word in lowered for word in LOCATION_WORDS):
                offending.append((tool.name, name))
    assert not offending, (
        f"{offending} publish a location-shaped parameter. The managed byte store "
        "takes no path at all and derives every location from opaque version "
        "identity; a caller-supplied location anywhere on this surface is the "
        "traversal WP-27 removed the parameter to prevent"
    )


def test_the_location_scan_would_catch_one() -> None:
    """`D-55`, on the scan itself rather than by planting in a command.

    A vocabulary this wide is worth checking against real spellings, because the
    failure mode is a word nobody thought of rather than a scan that does not run.
    """
    for spelling in ("path", "file_name", "targetDir", "managed_root", "objectURI", "SharePath"):
        assert any(word in spelling.lower() for word in LOCATION_WORDS), spelling
    for benign in ("title", "media_type", "document_id", "idempotency_key", "content"):
        assert not any(word in benign.lower() for word in LOCATION_WORDS), benign
    # The exemption is exactly one entry, it names a tool that exists, and the
    # property it names is really published — so it cannot rot into a permission
    # for a property that has since changed meaning or disappeared.
    assert len(EXEMPT_PROPERTIES) == 1
    for tool_name, property_name in EXEMPT_PROPERTIES:
        tool = next(entry for entry in TOOLS if entry.name == tool_name)
        assert property_name in set(_schema_property_names(tool.input_schema))


def test_no_payload_schema_publishes_a_principal() -> None:
    """The partition is never a wire parameter of a capability's own payload.

    `RequestMetadata.principal_id` is in the envelope half and is correlation
    input the application does not read — `test_principal_is_never_caller_supplied.py`
    is what keeps that true. What must never appear is a `principal_id` in a
    *payload*, because that is a field a handler could plausibly read as the
    partition to act in.
    """
    for tool in TOOLS:
        payload = tool.input_schema["properties"]["payload"]
        published = set(_schema_property_names(payload))
        forbidden = {name for name in published if "principal" in name.lower()}
        assert not forbidden, f"{tool.name} publishes {sorted(forbidden)} in its payload"


# ---- claim 6: stdio only ----------------------------------------------------


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_no_network_transport_is_reachable_from_the_package(path: Path) -> None:
    """`D-26`/`D-30`: stdio only, and the SDK ships the alternatives beside it."""
    imported = imported_modules(_tree(path))
    reachable = sorted(imported & NETWORK_MODULES)
    assert not reachable, (
        f"{_relative(path)} imports {reachable}. The MCP surface is stdio-only: "
        "no socket is opened, and the SDK's network transports are never imported"
    )
    # The allowlist already implies this, and the explicit form is kept because
    # the two fail for different reasons and a reader looking for "is a socket
    # possible" should find the answer under that name.
    assert not any(name.startswith(("mcp.server.sse", "mcp.server.stream")) for name in imported)


def test_the_network_module_set_names_things_that_exist() -> None:
    """The set is a description of the SDK's real surface, not a list of guesses."""
    import importlib.util

    installed = [
        name
        for name in ("mcp.server.sse", "mcp.server.streamable_http", "uvicorn", "starlette")
        if importlib.util.find_spec(name) is not None
    ]
    assert installed, (
        "none of the forbidden network modules is installed, so forbidding them "
        "proves nothing about this build"
    )


# ---- claim 4b: the two things per-capability logic cannot be written without --
#
# **Found by planting, not by design.** The first plant — a persistence import
# and a `repository.admit(...)` in the tool path — reddened claims 2 and 3 for the
# intended reasons. The second came back **green on the first attempt**: an
# expected-version comparison and an idempotency decision written inline in
# `_answer`, using nothing but names already on the allowlist. That is a real
# reimplementation, and none of the claims above could see it, because it imports
# nothing and calls nothing forbidden.
#
# What it *cannot* avoid is the two things any per-capability rule needs: it has
# to know which capability it is serving, and it has to read a field out of the
# caller's request. Neither is something a thin adapter ever does — the tool name
# goes to `normalize` as an opaque string and the arguments go as a whole
# document — so both can be forbidden outright rather than pattern-matched.


def _string_literals(tree: ast.AST) -> list[tuple[int, str]]:
    """Every string constant in `tree`, docstrings included.

    Docstrings are *not* skipped, deliberately, and the price is paid explicitly
    below: prose in this package may not spell a capability name as a bare
    string. WP-18's lesson was that a comment span hid whole lines from a text
    guard; the inverse mistake — excluding the places a literal could hide — is
    the one available here, so nothing is excluded.
    """
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_the_adapter_never_names_a_capability_it_serves(path: Path) -> None:
    """No literal in this package equals a capability name.

    A transport that branches on which capability it is serving is a transport
    with per-capability behaviour, and per-capability behaviour in an adapter is
    the parallel implementation by another route. The tool name reaches
    `normalize` as an opaque string and is compared against nothing here; the
    only place a capability name is written down is `Capability` itself, which
    `tools.py` reads as an enum.
    """
    from my_pa.domain.identity.operation import Capability, NativeSourceCapability

    names = {member.value for member in Capability} | {
        member.value for member in NativeSourceCapability
    }
    found = [(line, value) for line, value in _string_literals(_tree(path)) if value in names]
    assert not found, (
        f"{_relative(path)} writes {found}. A transport that can tell which "
        "capability it is serving can behave differently for one of them, which "
        "is per-capability logic beside the application rather than through it"
    )


#: Names bound to a caller's request document anywhere in this package. The
#: parameter `_document` takes, the local it binds, the SDK's request params, and
#: the three neutral spellings a future helper would reach for.
REQUEST_RECEIVERS: Final[frozenset[str]] = frozenset(
    {"arguments", "body", "document", "params", "payload", "request"}
)

#: How a field is read out of a mapping, beyond the subscript form.
ACCESSORS: Final[frozenset[str]] = frozenset({"get", "pop", "setdefault", "__getitem__", "items"})


def request_field_reads(tree: ast.AST) -> list[tuple[int, str]]:
    """Every read of a named field out of a caller's request, in either form.

    Subscript (`arguments["payload"]`) and accessor (`arguments.get("payload")`),
    including through a chain — `params.arguments.get(...)` roots at `params` and
    is reported. Rooting rather than matching the immediate receiver is what makes
    the second plant visible: it read `(arguments or {}).get("payload", {}).get(
    "idempotency_key")`, which no immediate-receiver check would have matched.
    """
    found: list[tuple[int, str]] = []

    def _root(node: ast.AST) -> str | None:
        while True:
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute | ast.Subscript):
                node = node.value
            elif isinstance(node, ast.Call):
                node = node.func
            elif isinstance(node, ast.BoolOp) and node.values:
                node = node.values[0]
            else:
                return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            root = _root(node.value)
            if root in REQUEST_RECEIVERS:
                found.append((node.lineno, f"{root}[...]"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr not in ACCESSORS:
                continue
            root = _root(node.func.value)
            if root in REQUEST_RECEIVERS:
                found.append((node.lineno, f"{root}.{node.func.attr}(...)"))
    return found


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_the_adapter_never_reads_a_field_out_of_a_request(path: Path) -> None:
    """The document goes to `normalize` whole, or it is not going through one path.

    Validation, idempotency and expected-version logic all begin by reading a
    field. `_document` measures the encoded size of the whole document and hands
    it on; nothing in this package looks inside it.
    """
    reads = request_field_reads(_tree(path))
    assert not reads, (
        f"{_relative(path)} reads {reads} out of a caller's request. The request "
        "document reaches `adapters.normalization` whole; a transport that opens "
        "it is validating, deciding, or routing on a payload — the second "
        "validation path `D-25` chose Starlette to avoid"
    )


def test_both_detectors_report_the_plant_that_got_through() -> None:
    """`D-55`, and the reason these two claims exist at all.

    The exact shape that passed every other claim in this file, kept verbatim so
    that the value of the control is what it caught rather than what it describes.
    """
    planted = ast.parse(
        "seen: dict[str, int] = {}\n"
        'if name == "documents.revise":\n'
        '    key = str((arguments or {}).get("payload", {}).get("idempotency_key"))\n'
        '    expected = (arguments or {}).get("payload", {}).get("expected_version_number")\n'
        "    if seen.get(key, 0) >= int(expected or 0):\n"
        "        raise InvalidRequestError()\n"
    )
    from my_pa.domain.identity.operation import Capability

    literals = {value for _, value in _string_literals(planted)}
    assert Capability.DOCUMENTS_REVISE.value in literals

    reads = request_field_reads(planted)
    assert reads, "the field-read detector does not see the plant it was written for"
    assert all(entry.startswith("arguments.") for _, entry in reads)

    # The other end of `D-55`: the real module passes both detectors, so they
    # distinguish rather than merely refuse.
    for path in _modules():
        tree = _tree(path)
        assert not request_field_reads(tree)
