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
   `rglob`, and the count is pinned — *and* the package is asserted to contain
   nothing but those files, because enumerating only the type you already scan is
   the mistake rather than the fix. WP-23's no-vector guard missed an entire file
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

And two more, at the foot of the file, which exist because a plant got past all
six and are now written to match *shapes* rather than spellings: this package
names no capability it serves (constant expressions are folded, so a composed
name is a name, and comparing against the enum is refused too) and reads no field
out of a caller's request (the request is followed through assignment, unpacking,
iteration and into helpers, so rebinding it to a differently-named local carries
it rather than losing it). `test_what_these_detectors_cannot_see` states their
reach, as a test, so that the disclosure fails when it stops being true.

Nothing here opens a connection, reaches a source, or touches a database.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Final

import pytest

from my_pa.adapters.mcp.tools import TOOLS

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa" / "adapters" / "mcp"

#: Every module in the package, by name. Written out so that a new module is a
#: decision recorded here rather than a file that quietly joins the scan — or,
#: worse, one the scan never notices it did not read.
MODULES: Final[frozenset[str]] = frozenset({"__init__.py", "remote.py", "server.py", "tools.py"})

#: Exactly what this package may import from this repository. An allowlist, in
#: the `D-81` shape: an entry that no longer matches reddens, and a new import is
#: a decision written here beside the reason it is admissible.
#:
#: What each one is, and why reaching it is not reaching an implementation:
#:
#: * `adapters.normalization` — the one shared `(metadata, command)` builder all
#:   three transports call. Reaching it is the *point*; a transport that did not
#:   would be building its own request pair.
#: * `adapters.remote_request` — remote MCP envelope composition. It stamps
#:   server-owned metadata and refuses caller copies; it does not authorize.
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
        "my_pa.adapters.mcp.remote",
        "my_pa.adapters.mcp.tools",
        "my_pa.adapters.normalization",
        "my_pa.adapters.remote_request",
        "my_pa.application.commands",
        "my_pa.application.errors",
        "my_pa.application.service",
        "my_pa.contracts.v1.envelope",
        "my_pa.contracts.v1.errors",
        "my_pa.domain.common.identifiers",
        "my_pa.domain.common.time",
        "my_pa.domain.identity.operation",
        "my_pa.domain.identity.principal",
        "my_pa.domain.identity.purpose",
        "my_pa.domain.capture.submission",
        "my_pa.domain.documents.managed",
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
        "contextlib",
        "dataclasses",
        "datetime",
        "enum",
        "json",
        "mcp.server.context",
        "mcp.server.lowlevel",
        "mcp.server.stdio",
        "mcp.server.streamable_http_manager",
        "mcp.server.transport_security",
        "mcp.types",
        "starlette.applications",
        "starlette.requests",
        "starlette.responses",
        "starlette.routing",
        "starlette.types",
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
#:
#: `compile`, `eval`, `exec` and `getattr` are here for a different reason and it
#: is worth writing down: they are how the two detectors at the foot of this file
#: would be evaded rather than defeated. A capability name inside a string that is
#: later `exec`ed is not a constant expression, and a forbidden method reached as
#: `getattr(store, "".join(…))` is not an `ast.Attribute`. Neither is anything a
#: thin adapter has a use for, so both are refused here instead of being chased
#: through a scan that cannot follow them.
FORBIDDEN_CALLS: Final[frozenset[str]] = frozenset(
    {
        "accept",
        "admit",
        "authorize",
        "commit",
        "compile",
        "connect",
        "create_engine",
        "eval",
        "evaluate",
        "exec",
        "execute",
        "getattr",
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


#: The properties the vocabulary above matches that are **not** a location, with
#: the reason they are not — an exemption list in the `D-81` shape, so a further
#: one is a decision somebody writes down beside this sentence.
#:
#: `sources.enroll`'s `root_object_id` is an opaque `obj_…` source-object
#: identifier: it names a node in a source's own object graph, is minted by this
#: product, and is resolved by the provider through `knowledge.source_objects`.
#: It is matched only because "root" is in the vocabulary, and "root" stays in
#: the vocabulary because it is the word `managed_root` and `native_root` are
#: spelled with — removing it to silence this one entry would blind the scan to
#: the two names that would actually matter.
#:
#: `context.feedback`'s `target_id` is an opaque identifier of the same shape
#: as `knowledge.reveal`'s `subject_id`. It is matched only because "target" is
#: in the vocabulary; it names no filesystem path and is validated for shape
#: only.
EXEMPT_PROPERTIES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("sources.enroll", "root_object_id"),
        ("context.feedback", "target_id"),
    }
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
    assert len(modules) == 4, f"the package now holds {[p.name for p in modules]}"
    # A positive control on the parser: the package really does contain code, so
    # the AST claims below are about statements rather than about empty files.
    statements = sum(len(list(ast.walk(_tree(path)))) for path in modules)
    assert statements > 500, f"only {statements} AST nodes were parsed"


def test_the_package_holds_nothing_this_scan_cannot_read() -> None:
    """The other half of a closed universe: `*.py` is the whole of what is there.

    Every claim below is an `ast.parse` of a `.py` file, so a file of any other
    kind in this package is a file no claim in this file has an opinion about.
    That is exactly WP-23's failure — a guard that could not see `.sql` at all —
    and it is not enough to enumerate the files of the type you already scan. So
    the enumeration is made against *every* entry under the package: a `.pyi`
    stub, a `.json` table a dispatcher could read, a `.so`, or a data file
    carrying per-capability rules would each redden here rather than pass
    unexamined.

    `__pycache__` is excluded because it is a build product of the files above
    it, and `py.typed` would be a decision to record here beside this sentence.
    """
    entries = sorted(
        path for path in PACKAGE.rglob("*") if "__pycache__" not in path.parts and not path.is_dir()
    )
    unreadable = [_relative(path) for path in entries if path.suffix != ".py"]
    assert not unreadable, (
        f"{unreadable} are in this package and no claim in this file reads them. "
        "Every scan here is an `ast.parse` of Python: a file of another kind is "
        "a place per-capability behaviour could live unexamined"
    )
    assert {path.name for path in entries} == MODULES
    directories = {
        path for path in PACKAGE.rglob("*") if path.is_dir() and "__pycache__" not in path.parts
    }
    assert not directories, (
        f"the package now has subpackages: {sorted(map(_relative, directories))}"
    )


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
    assert len(FORBIDDEN_CALLS) == 17
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
    called = {name for _, name in called_names(handler)}
    assert {"run_in_executor", "CallToolResult"} <= called
    assert any(isinstance(node, ast.Name) and node.id == "_answer" for node in ast.walk(handler))
    assert "invoke" not in called
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
    # The exemption names tools that exist, and the properties they name are
    # really published — so it cannot rot into a permission for a property that
    # has since changed meaning or disappeared.
    assert len(EXEMPT_PROPERTIES) == 2
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
    if path.name == "remote.py":
        return
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
#
# **Both detectors were then defeated, and the correction is the shape rather
# than the two spellings.** WP-28's independent reviewer re-planted the same
# reimplementation with two changes and every test in this file stayed green: the
# capability name written as `"documents" + "." + "revise"`, which is an
# `ast.BinOp` and not a literal a whole-string scan can see; and the request
# rebound to a local called `carried`, which a fixed list of receiver names cannot
# see. Both detectors matched *names*. So:
#
# * the literal scan now **folds constant expressions** — concatenation,
#   `str.join`, f-strings, `%`, `.format` and the pure string methods, through
#   names bound once to a constant — and matches the folded value;
# * the field-read scan now **follows data flow**: a parameter a request arrives
#   in taints every local it reaches, through assignment, unpacking, iteration,
#   `with`, and a call into another function in the same module. The name of the
#   local is irrelevant, which is why `tools.py` can call a local holding type
#   arguments `arguments` again;
# * naming a capability through the enum rather than as text — `Capability.
#   DOCUMENTS_REVISE.value` — is forbidden in a comparison, because that spelling
#   needs no string at all.
#
# What none of this reaches is written down in
# `test_what_these_detectors_cannot_see`, which is a test so that the disclosure
# cannot drift away from the code.


#: Pure string methods a constant may be put through and still be a constant.
#: Every one is total on strings and free of side effects, so folding through it
#: is evaluation rather than execution.
STRING_METHODS: Final[frozenset[str]] = frozenset(
    {
        "casefold",
        "format",
        "join",
        "lower",
        "lstrip",
        "removeprefix",
        "removesuffix",
        "replace",
        "rstrip",
        "strip",
        "swapcase",
        "title",
        "upper",
    }
)

#: How many times a constant may be repeated by `*` before folding gives up. A
#: ceiling rather than a refusal, so `"ab" * 3` folds and `"ab" * 10**9` does not
#: build a gigabyte inside a test.
REPEAT_CEILING: Final = 64


def _fold_sequence(
    node: ast.AST, strings: Mapping[str, str], sequences: Mapping[str, tuple[str, ...]]
) -> tuple[str, ...] | None:
    """The tuple of strings a constant sequence evaluates to, or `None`.

    Exists for `str.join`, which is how a capability name is composed without an
    operator: `".".join(("documents", "revise"))`, and the same with the sequence
    bound to a name first.
    """
    if isinstance(node, ast.Name):
        return sequences.get(node.id)
    if not isinstance(node, ast.List | ast.Tuple):
        return None
    folded: list[str] = []
    for element in node.elts:
        value = _fold(element, strings, sequences)
        if value is None:
            return None
        folded.append(value)
    return tuple(folded)


def _fold_binary(
    node: ast.BinOp, strings: Mapping[str, str], sequences: Mapping[str, tuple[str, ...]]
) -> str | None:
    """`+`, `%` and `*` over constants."""
    left = _fold(node.left, strings, sequences)
    right = _fold(node.right, strings, sequences)
    if isinstance(node.op, ast.Add):
        return None if left is None or right is None else left + right
    if isinstance(node.op, ast.Mod) and left is not None:
        operand: object
        if isinstance(node.right, ast.Tuple):
            values = _fold_sequence(node.right, strings, sequences)
            if values is None:
                return None
            operand = values
        elif right is None:
            return None
        else:
            operand = right
        try:
            return left % operand
        except (TypeError, ValueError, KeyError):
            return None
    if isinstance(node.op, ast.Mult):
        for text, other in ((left, node.right), (right, node.left)):
            if text is None or not isinstance(other, ast.Constant):
                continue
            count = other.value
            if isinstance(count, bool) or not isinstance(count, int):
                continue
            if 0 <= count <= REPEAT_CEILING:
                return text * count
    return None


def _fold_method(
    node: ast.Call, strings: Mapping[str, str], sequences: Mapping[str, tuple[str, ...]]
) -> str | None:
    """`"…".join(…)`, `"…".format(…)`, `"…".lower()` and the rest of `STRING_METHODS`."""
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in STRING_METHODS:
        return None
    receiver = _fold(node.func.value, strings, sequences)
    if receiver is None:
        return None
    positional: list[object] = []
    for argument in node.args:
        sequence = _fold_sequence(argument, strings, sequences)
        if node.func.attr == "join" and sequence is not None:
            positional.append(sequence)
            continue
        value = _fold(argument, strings, sequences)
        if value is None:
            return None
        positional.append(value)
    keywords: dict[str, str] = {}
    for keyword in node.keywords:
        value = _fold(keyword.value, strings, sequences)
        if keyword.arg is None or value is None:
            return None
        keywords[keyword.arg] = value
    try:
        result = getattr(receiver, node.func.attr)(*positional, **keywords)
    except (TypeError, ValueError, KeyError, IndexError, AttributeError):
        return None
    return result if isinstance(result, str) else None


def _fold(
    node: ast.AST, strings: Mapping[str, str], sequences: Mapping[str, tuple[str, ...]]
) -> str | None:
    """The string a constant expression evaluates to, or `None` if it is not one.

    Constant folding rather than literal matching, because `"documents" + "." +
    "revise"` is not a literal and reads exactly like one. Covers concatenation,
    repetition, `%`, f-strings, `str.join`, `str.format` and the pure string
    methods, over constants and over names bound once to a constant.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Name):
        return strings.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for piece in node.values:
            if isinstance(piece, ast.FormattedValue):
                value = _fold(piece.value, strings, sequences)
            elif isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                value = piece.value
            else:
                return None
            if value is None:
                return None
            parts.append(value)
        return "".join(parts)
    if isinstance(node, ast.BinOp):
        return _fold_binary(node, strings, sequences)
    if isinstance(node, ast.Call):
        return _fold_method(node, strings, sequences)
    return None


def _bound_names(targets: Iterable[ast.AST]) -> set[str]:
    """The plain names an assignment target binds, through tuples and stars.

    An attribute or a subscript target binds nothing new — it mutates something
    that already exists — so neither contributes a name here.
    """
    found: set[str] = set()
    for target in targets:
        if isinstance(target, ast.Name):
            found.add(target.id)
        elif isinstance(target, ast.Tuple | ast.List):
            found |= _bound_names(target.elts)
        elif isinstance(target, ast.Starred):
            found |= _bound_names([target.value])
    return found


def _parameters(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    arguments = function.args
    named = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    return named + [entry for entry in (arguments.vararg, arguments.kwarg) if entry is not None]


def _module_bindings(tree: ast.AST) -> set[str]:
    """Every name this module binds itself, however it binds it.

    Used to decide which receiver names are *free* — handed in from outside the
    module and therefore a request — as opposed to locals the module minted. It is
    what lets `tools.py` bind a local called `arguments` to a tuple of type
    arguments without the scan calling it a caller's request.
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            bound |= _bound_names(node.targets)
        elif isinstance(
            node,
            ast.AnnAssign
            | ast.AugAssign
            | ast.NamedExpr
            | ast.For
            | ast.AsyncFor
            | ast.comprehension,
        ):
            bound |= _bound_names([node.target])
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            bound |= _bound_names([node.optional_vars])
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            bound.add(node.name)
            bound |= {entry.arg for entry in _parameters(node)}
        elif isinstance(node, ast.ClassDef):
            bound.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            bound |= {(alias.asname or alias.name).split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.Lambda):
            bound |= {entry.arg for entry in (*node.args.args, *node.args.kwonlyargs)}
    return bound


def _constants(tree: ast.AST) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    """Names this module binds exactly once to a constant, as two environments.

    Single assignment only, and never a name the module also rebinds by iteration
    or by parameter, so the environment describes constants rather than guesses at
    what a variable held at some point. Three passes, so a chain — `A = "docu"`,
    `B = A + "ments"`, `C = B + ".revise"` — settles.
    """
    rebound: set[str] = set()
    assigned: dict[str, list[ast.expr]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for name in _bound_names(node.targets):
                assigned.setdefault(name, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            for name in _bound_names([node.target]):
                assigned.setdefault(name, []).append(node.value)
        elif isinstance(
            node, ast.AugAssign | ast.NamedExpr | ast.For | ast.AsyncFor | ast.comprehension
        ):
            rebound |= _bound_names([node.target])
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            rebound |= _bound_names([node.optional_vars])
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            rebound |= {entry.arg for entry in _parameters(node)}
    strings: dict[str, str] = {}
    sequences: dict[str, tuple[str, ...]] = {}
    for _pass in range(3):
        for name, values in assigned.items():
            if len(values) != 1 or name in rebound:
                continue
            folded = _fold(values[0], strings, sequences)
            if folded is not None:
                strings[name] = folded
            sequence = _fold_sequence(values[0], strings, sequences)
            if sequence is not None:
                sequences[name] = sequence
    return strings, sequences


def folded_strings(tree: ast.AST) -> list[tuple[int, str]]:
    """Every string any constant expression in `tree` evaluates to, as `(line, value)`.

    Docstrings are *not* skipped, deliberately, and the price is paid explicitly
    below: prose in this package may not spell a capability name as a bare
    string. WP-18's lesson was that a comment span hid whole lines from a text
    guard; the inverse mistake — excluding the places a literal could hide — is
    the one available here, so nothing is excluded.
    """
    strings, sequences = _constants(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant | ast.Name | ast.JoinedStr | ast.BinOp | ast.Call):
            continue
        value = _fold(node, strings, sequences)
        if value is not None:
            found.append((node.lineno, value))
    return found


def capability_names() -> frozenset[str]:
    """Every capability name, plus the family prefix each one belongs to.

    The prefix is here because `name.startswith("documents.")` is per-capability
    branching a whole-name match would not see, and `"documents."` is a string no
    prose in this package writes on its own.
    """
    from my_pa.domain.identity.operation import Capability, NativeSourceCapability

    values = {member.value for member in Capability} | {
        member.value for member in NativeSourceCapability
    }
    return frozenset(values | {f"{value.split('.')[0]}." for value in values})


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_the_adapter_never_names_a_capability_it_serves(path: Path) -> None:
    """No constant expression in this package evaluates to a capability name.

    A transport that branches on which capability it is serving is a transport
    with per-capability behaviour, and per-capability behaviour in an adapter is
    the parallel implementation by another route. The tool name reaches
    `normalize` as an opaque string and is compared against nothing here; the
    only place a capability name is written down is `Capability` itself, which
    `tools.py` reads as an enum.
    """
    names = capability_names()
    found = [(line, value) for line, value in folded_strings(_tree(path)) if value in names]
    assert not found, (
        f"{_relative(path)} writes {found}. A transport that can tell which "
        "capability it is serving can behave differently for one of them, which "
        "is per-capability logic beside the application rather than through it"
    )


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_the_adapter_never_compares_against_a_capability_member(path: Path) -> None:
    """The spelling that needs no string at all.

    `Capability.DOCUMENTS_REVISE.value` composes no literal and folds to nothing,
    so the scan above cannot see it. What it cannot avoid is being *compared* —
    per-capability behaviour is a branch — so a comparison with an operand reached
    through the enum is what reddens here. `tools.py` reads the enum to build the
    tool list and compares nothing, and `published_tools` filters on a set built
    from the service rather than on a member named here.
    """
    enums = {"Capability", "NativeSourceCapability"}

    def _roots(node: ast.AST) -> set[str]:
        if isinstance(node, ast.Name):
            return {node.id}
        if isinstance(node, ast.Attribute | ast.Subscript | ast.Starred):
            return _roots(node.value)
        return set()

    offending: list[tuple[int, str]] = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Compare):
            continue
        for operand in (node.left, *node.comparators):
            if _roots(operand) & enums:
                offending.append((node.lineno, ast.unparse(operand)))
    assert not offending, (
        f"{_relative(path)} compares against {offending}. Naming one capability "
        "through the enum is the same per-capability branch as naming it as a "
        "string, and this package makes neither"
    )


#: Names a caller's request arrives in. Seeds for the data-flow scan below rather
#: than the scan itself: a *parameter* with one of these names is a request, and
#: so is one of these names the module never binds at all. A local the module
#: binds to something of its own is not, whatever it is called.
REQUEST_RECEIVERS: Final[frozenset[str]] = frozenset(
    {"arguments", "body", "document", "params", "payload", "request"}
)

#: How a field is read out of a mapping, beyond the subscript form. Both the
#: bound spelling (`carried.get(…)`) and the unbound one (`dict.get(carried, …)`,
#: `operator.getitem(carried, …)`), which is why the scan below looks at the first
#: positional argument as well as at the receiver.
ACCESSORS: Final[frozenset[str]] = frozenset(
    {"get", "getitem", "items", "keys", "pop", "setdefault", "values", "__getitem__"}
)


def _mentions(node: ast.AST, tainted: frozenset[str] | set[str]) -> bool:
    return any(isinstance(inner, ast.Name) and inner.id in tainted for inner in ast.walk(node))


def _reached_parameters(
    function: ast.FunctionDef | ast.AsyncFunctionDef, call: ast.Call, tainted: set[str]
) -> set[str]:
    """The parameters of `function` a tainted argument at `call` would arrive in."""
    positional = [entry.arg for entry in (*function.args.posonlyargs, *function.args.args)]
    named = set(positional) | {entry.arg for entry in function.args.kwonlyargs}
    reached: set[str] = set()
    for index, argument in enumerate(call.args):
        if not _mentions(argument, tainted):
            continue
        if index < len(positional):
            reached.add(positional[index])
        elif function.args.vararg is not None:
            reached.add(function.args.vararg.arg)
    for keyword in call.keywords:
        if not _mentions(keyword.value, tainted):
            continue
        if keyword.arg in named:
            reached.add(keyword.arg)
        elif function.args.kwarg is not None:
            reached.add(function.args.kwarg.arg)
    return reached


def request_taint(tree: ast.AST) -> frozenset[str]:
    """Every name in this module that a caller's request document flows into.

    Seeded from the *shape* of a request rather than from a list of local names:
    a parameter called one of `REQUEST_RECEIVERS`, and a free name of the same
    spelling the module never binds. It then propagates to a fixpoint through
    assignment, tuple unpacking, augmented assignment, walrus, `for`,
    comprehensions, `with … as`, and a call into another function defined in the
    same module — so rebinding a request to a differently-named local, or handing
    it to a helper, carries the taint rather than losing it.

    Deliberately coarse in one direction: a name that *mentions* a tainted name
    anywhere in its right-hand side is tainted, because a transport that derives
    anything from a request and then indexes into it is doing the thing this
    forbids. Module-wide rather than per-scope, which is conservative in the same
    direction.
    """
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    bound = _module_bindings(tree)
    loaded = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    tainted: set[str] = {name for name in REQUEST_RECEIVERS if name in loaded and name not in bound}
    for function in functions.values():
        tainted |= {entry.arg for entry in _parameters(function) if entry.arg in REQUEST_RECEIVERS}

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            reached: set[str] = set()
            if isinstance(node, ast.Assign) and _mentions(node.value, tainted):
                reached = _bound_names(node.targets)
            elif isinstance(node, ast.AnnAssign | ast.AugAssign) and node.value is not None:
                if _mentions(node.value, tainted):
                    reached = _bound_names([node.target])
            elif isinstance(node, ast.NamedExpr) and _mentions(node.value, tainted):
                reached = _bound_names([node.target])
            elif isinstance(node, ast.For | ast.AsyncFor | ast.comprehension):
                if _mentions(node.iter, tainted):
                    reached = _bound_names([node.target])
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                if _mentions(node.context_expr, tainted):
                    reached = _bound_names([node.optional_vars])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called = functions.get(node.func.id)
                if called is not None:
                    reached = _reached_parameters(called, node, tainted)
            if not reached <= tainted:
                tainted |= reached
                changed = True
    return frozenset(tainted)


def _receivers(node: ast.AST) -> set[str]:
    """Every name the value of `node` could have been read out of.

    Through attributes, subscripts, `or`/`and`, a conditional, and a call's
    callable *and* its arguments — so `dict(carried).get(...)` and `(arguments or
    {}).get(...)` both report the name the document arrived in.
    """
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute | ast.Subscript | ast.Starred):
        return _receivers(node.value)
    if isinstance(node, ast.BoolOp):
        return set().union(*(_receivers(value) for value in node.values))
    if isinstance(node, ast.IfExp):
        return _receivers(node.body) | _receivers(node.orelse)
    if isinstance(node, ast.Call):
        found = _receivers(node.func)
        for argument in node.args:
            found |= _receivers(argument)
        for keyword in node.keywords:
            found |= _receivers(keyword.value)
        return found
    return set()


def request_field_reads(tree: ast.AST) -> list[tuple[int, str]]:
    """Every read of a named field out of a caller's request, in either form.

    Subscript (`arguments["payload"]`) and accessor (`arguments.get("payload")`),
    against the *tainted* set rather than against a list of names — which is what
    makes a rebinding visible: `carried = arguments` followed by `carried.get(…)`
    reports `carried`, and so does a helper that took the document as `doc`.
    """
    tainted = request_taint(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            reached = sorted(_receivers(node.value) & tainted)
            if reached:
                found.append((node.lineno, f"{reached[0]}[...]"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr not in ACCESSORS:
                continue
            # The receiver, and the first positional argument: an accessor called
            # unbound — `dict.get(carried, "payload")` — puts the document there
            # instead, and the receiver is then a type rather than the request.
            instance = _receivers(node.func.value)
            if node.args:
                instance |= _receivers(node.args[0])
            reached = sorted(instance & tainted)
            if reached:
                found.append((node.lineno, f"{reached[0]}.{node.func.attr}(...)"))
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


#: The reimplementation that got through, in the two spellings that got it
#: through: the capability name composed out of an `ast.BinOp` rather than
#: written, and the request rebound to a local the old receiver list did not
#: name. Kept verbatim, and wrapped in the signature `_answer` really has, because
#: the value of a control is what it caught rather than what it describes.
EVADING_PLANT: Final = """
def _answer(service, principal, name, arguments):
    seen: dict[str, int] = {}
    carried = arguments or {}
    if name == "documents" + "." + "revise":
        key = str(carried.get("payload", {}).get("idempotency_key"))
        expected = carried.get("payload", {}).get("expected_version_number")
        if seen.get(key, 0) >= int(expected or 0):
            raise InvalidRequestError()
        if carried.get("payload", {}).get("state") == "archived":
            raise InvalidRequestError()
        if not principal.principal_id.startswith("prn_"):
            raise InvalidRequestError()
    return "", False
"""


def test_both_detectors_report_the_plant_that_got_through() -> None:
    """`D-55`, and the reason these two claims exist at all.

    The shape that passed every other claim in this file *and then passed these
    two as well*, until they were made to follow values instead of names.
    """
    planted = ast.parse(EVADING_PLANT)
    names = capability_names()

    folded = {value for _, value in folded_strings(planted)}
    assert names & folded, "the capability scan does not fold the composed name"

    reads = request_field_reads(planted)
    assert reads, "the field-read detector does not see the plant it was written for"
    # Reported under the name the request was *rebound* to, which is the half the
    # old detector could not reach: it rooted at a fixed list that `carried` was
    # not on. The plant's own derived locals are reported too — a key read out of
    # a payload is still a payload — and that is the taint doing its work rather
    # than a second finding.
    assert any(entry.startswith("carried.") for _, entry in reads)

    # The other end of `D-55`: the real module passes both detectors, so they
    # distinguish rather than merely refuse.
    for path in _modules():
        tree = _tree(path)
        assert not request_field_reads(tree)


@pytest.mark.parametrize(
    ("composed", "expected"),
    [
        ('"documents" + "." + "revise"', "documents.revise"),
        ('".".join(("documents", "revise"))', "documents.revise"),
        ('PARTS = ("documents", "revise")\nNAME = ".".join(PARTS)', "documents.revise"),
        ('WHICH = "revise"\nNAME = f"documents.{WHICH}"', "documents.revise"),
        ('"documents.%s" % "revise"', "documents.revise"),
        ('"{}.{}".format("documents", "revise")', "documents.revise"),
        ('"DOCUMENTS.REVISE".lower()', "documents.revise"),
        ('"documents!revise".replace("!", ".")', "documents.revise"),
        ('"xdocuments.revisex".strip("x")', "documents.revise"),
        ('FIRST = "docu"\nSECOND = FIRST + "ments"\nNAME = SECOND + ".revise"', "documents.revise"),
        ('FAMILY = "documents" + "."', "documents."),
    ],
)
def test_the_capability_scan_folds_the_spellings_that_are_not_literals(
    composed: str, expected: str
) -> None:
    """`D-55` on the folder itself, over the shapes a name can be composed in.

    Each entry is a way of writing a capability name that no whole-literal scan
    would match, and every one of them has to fold to the name for the claim above
    to be about behaviour rather than about typography.
    """
    assert expected in {value for _, value in folded_strings(ast.parse(composed))}
    assert expected in capability_names()


@pytest.mark.parametrize(
    "rebinding",
    [
        "def f(arguments):\n    carried = arguments\n    return carried.get('payload')",
        "def f(arguments):\n    a, b = arguments, None\n    return a['payload']",
        "def f(arguments):\n    for entry in (arguments,):\n        return entry.get('payload')",
        "def f(arguments):\n    return [d['payload'] for d in (arguments,)]",
        "def f(arguments):\n    if (held := arguments):\n        return held.get('payload')",
        "def f(arguments):\n    return dict(arguments).get('payload')",
        "def _peek(doc):\n    return doc.get('payload')\n\n"
        "def f(arguments):\n    return _peek(arguments)",
        "def _peek(*rest):\n    return rest[0].get('payload')\n\n"
        "def f(arguments):\n    return _peek(arguments)",
        "def f(arguments):\n    return dict.get(arguments, 'payload')",
        "import operator\n\ndef f(arguments):\n    return operator.getitem(arguments, 'payload')",
    ],
)
def test_the_field_read_scan_follows_the_request_through_a_rebinding(rebinding: str) -> None:
    """`D-55` on the taint, over the ways a request can change its name.

    The evasion that defeated the first version of this detector was one line —
    assign the arguments to a local nobody listed — so the claim is checked
    against ten of them, including through a helper whose parameter has a name
    the seed list does not contain, and the unbound accessor form that puts the
    document in an argument rather than in the receiver.
    """
    assert request_field_reads(ast.parse(rebinding))


def test_what_these_detectors_cannot_see() -> None:
    """The reach of the control, written as a test so it cannot drift.

    A guard that catches everything is not the claim. These are shapes that were
    tried against the corrected detectors and **were not caught**, recorded here
    with the reason each is still not a way to smuggle business logic in
    unnoticed. If one of them ever starts being caught, this test reddens and the
    disclosure gets rewritten rather than quietly aged.
    """
    # 1. A name assembled from something that is not a constant — a character
    #    code, a slice of another module's data, an environment variable. Folding
    #    is evaluation of constants, not execution.
    assert not [
        value
        for _, value in folded_strings(ast.parse('NAME = chr(100) + "ocuments.revise"'))
        if value in capability_names()
    ]
    # 2. A request read through a value this module did not derive from the
    #    request — a mapping handed back by a call whose argument was not tainted.
    #    Nothing in this package has such a source, and claim 2's import allowlist
    #    is what keeps a new one from appearing.
    assert not request_field_reads(ast.parse("def f():\n    return elsewhere()['payload']"))
    # 3. Code inside a string that is later executed. `exec` and `eval` are in
    #    `FORBIDDEN_CALLS` for exactly this reason, so the shape is refused by
    #    claim 3 rather than by these two — which is the point of having both.
    assert {"eval", "exec"} <= FORBIDDEN_CALLS
    # 3b. An accessor built as a value rather than called by name —
    #    `itemgetter("payload")(carried)`. The call's callable is a call, so there
    #    is no accessor name to match; `operator` is not on claim 2's import
    #    allowlist, which is what actually refuses it.
    assert not request_field_reads(
        ast.parse("def f(arguments):\n    return itemgetter('payload')(arguments)")
    )
    assert "operator" not in ADMISSIBLE_IMPORTS | ADMISSIBLE_FOREIGN_IMPORTS
    # 4. The WP-18 shape — logic hidden behind a leading block comment — is not a
    #    blind spot here and could not be: a comment is not in the tree because it
    #    is not code, and a plant inside one does not run either. A plant inside a
    #    *docstring* is a string constant, and if that string is a capability name
    #    it reddens like any other.
    hidden = ast.parse('# if name == "documents.revise": pass\ndef f(arguments):\n    return None')
    assert not request_field_reads(hidden)
    assert not [value for _, value in folded_strings(hidden) if value in capability_names()], (
        "a comment is not code, and this asserts the scan is not pretending otherwise"
    )
