"""The acting Principal is derived from validated identity, never read from the caller.

WP-04, MU-AC-02, and `docs/specs` section 8.2. A caller-supplied identifier may
*arrive* — `RequestMetadata.principal_id` is a required field on every public
request, the CLI has a `--principal-id` flag, and the MCP tool schema publishes
the same envelope — and none of that is a defect. `RequestMetadata`'s own
docstring says why: the field is correlation input. The defect would be a
production module that *read* it and acted on it, because at that point the
caller has named the partition its request runs in.

Today there are zero such reads. That is a measurement, not a design intention,
and this module is what keeps it one. The acting Principal comes from
`bootstrap.gateway.local_principal` — derived from the durable local-operator
binding — reaches `application.authorize` as a `Principal`, and leaves it inside
an `Authorization`. Every use case reads
`authorization.principal.principal_id`. Nothing else is a source of identity.

Three claims:

1. **No production module reads a principal identity from a caller-supplied
   container.** Envelope metadata, request bodies, headers, query and path
   parameters, CLI namespaces, and MCP tool-argument mappings, in both the
   attribute and the subscript form.
2. **Where a caller-supplied `principal_id` is read at all, it is read to be
   verified, and the sites are registered exactly.** Three modules compare a
   request's stated owner against the server-resolved one and refuse a
   mismatch; a fourth reads a continuity command's first field. A fifth site
   has to be argued about here.
3. **A continuity command is never built from caller input.**
   `OpenSituationCommand` and its six siblings take `principal_id` as their
   first field and are unwired: no transport constructs one. When one is wired,
   the `principal_id=` it is given must be an attribute chain ending in
   `.principal.principal_id` — the Principal the authorization already
   resolved — and this test fails if it is anything else, including
   `metadata.principal_id`.

Live Entra readiness is WP-05's; nothing here asserts anything about token
validation. It asserts only that whatever the composition root resolves is the
only thing the rest of the tree reads.

Nothing here opens a connection, reaches a source, or touches a database.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"

#: The field names that name a principal, in every vocabulary this tree uses.
PRINCIPAL_FIELDS: Final = frozenset({"principal_id", "capture_principal_id", "principalId"})

#: Containers a caller controls. A `principal_id` read off any of these — as an
#: attribute or as a mapping key — is identity taken from payload.
#:
#: `metadata` is the first entry and the reason the list exists:
#: `RequestMetadata.principal_id` is a validated, well-formed identifier that
#: arrives on every request, which is exactly what makes reading it look
#: harmless.
CALLER_SUPPLIED: Final = frozenset(
    {
        "metadata",
        "request_metadata",
        "envelope",
        "body",
        "payload",
        "headers",
        "header",
        "cookies",
        "query",
        "query_params",
        "path_params",
        "params",
        "form",
        "arguments",
        "tool_arguments",
        "argv",
        "namespace",
        "raw",
        "untrusted",
    }
)

#: The seven R5 continuity commands. Each carries `principal_id` as its first
#: field and none is reachable from a transport yet, which is why the third
#: claim below is currently a zero.
CONTINUITY_COMMANDS: Final = frozenset(
    {
        "OpenSituationCommand",
        "CloseSituationCommand",
        "EnterFrameCommand",
        "AddProjectCommand",
        "LinkSituationToProjectCommand",
        "RecordRelationshipEventCommand",
        "TraceObjectCommand",
    }
)

#: An expression is a derived principal when it ends in one of these chains.
#: `.principal.principal_id` is an `Authorization`'s or a policy request's;
#: `account.principal_id` is the identity plane's registered account.
DERIVED_CHAINS: Final = ("principal.principal_id", "account.principal_id")

#: Every production read of a caller-supplied `principal_id` argument, as
#: `module -> ((receiver, field), ...)` sorted with multiplicity.
#:
#: Each of these reads a value the caller *stated* — and none of them trusts it.
#: `capture.py`, `enrollment.py`, and `review.py` compare the stated owner
#: against the server-resolved Principal and refuse a mismatch as
#: `CallerSuppliedPrincipalError`; `relationships.py` does the same for the
#: deciding Principal of an identity review (WP-04). `situation_service.py`
#: reads a continuity command's first field, and that command is unwired —
#: claim 3 is what keeps it from being wired unsafely.
#:
#: The registry is exact. A sixth module reading a request's stated principal is
#: a decision that has to be written here, with what verifies it.
VERIFIED_CALLER_STATEMENTS: Final = {
    "application/situation_service.py": (
        ("cmd", "principal_id"),
        ("cmd", "principal_id"),
        ("cmd", "principal_id"),
        ("cmd", "principal_id"),
        ("cmd", "principal_id"),
        ("cmd", "principal_id"),
        ("cmd", "principal_id"),
        ("cmd", "principal_id"),
    ),
    "infrastructure/persistence/capture.py": (
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
    ),
    "infrastructure/persistence/enrollment.py": (
        ("request", "principal_id"),
        ("request", "principal_id"),
    ),
    "infrastructure/persistence/review.py": (
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
    ),
}

#: Receivers that are not caller-supplied at all, and why. Everything not named
#: here and not in `CALLER_SUPPLIED` is an internal object.
_DERIVED_RECEIVERS: Final = frozenset(
    {
        "self",  # a dataclass validating its own field
        "principal",  # the resolved Principal
        "authorization",  # carries the resolved Principal
        "context",  # a PrincipalContext or an application context
        "resolved",  # the output of `require_principal_context`
        "account",  # a registered UserAccount
        "event",  # a domain audit event
        "row",  # a database row
        "mapping",  # a database row mapping
        "c",  # a table's column collection
    }
)


def _modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def _relative(path: Path) -> str:
    return str(path.relative_to(PACKAGE))


def _root_name(node: ast.expr) -> str | None:
    """The nearest named receiver of an attribute or subscript chain."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _root_name(node.func)
    if isinstance(node, ast.Subscript):
        return _root_name(node.value)
    return None


def _chain_names(node: ast.expr) -> frozenset[str]:
    """Every identifier appearing anywhere in one attribute/subscript/call chain.

    The whole chain rather than its nearest receiver, because a caller-supplied
    container reached through a call — `headers.get("x")["principal_id"]` — has
    `get` as its nearest name and `headers` as the thing that made it
    untrusted.
    """
    return frozenset(
        {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
        | {child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)}
    )


def caller_supplied_reads(tree: ast.AST) -> tuple[tuple[int, str], ...]:
    """Every `principal_id` read off a caller-supplied container in `tree`.

    Public, because this module's own control runs it over a synthetic tree that
    really does contain one. A detector that found nothing would otherwise agree
    with the production zero for the wrong reason.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        named = (isinstance(node, ast.Attribute) and node.attr in PRINCIPAL_FIELDS) or (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value in PRINCIPAL_FIELDS
        )
        if not named or not isinstance(node, ast.Attribute | ast.Subscript):
            continue
        if _chain_names(node.value) & CALLER_SUPPLIED:
            found.append((node.lineno, ast.unparse(node)))
    return tuple(found)


def _stated_principal_reads(tree: ast.AST) -> tuple[tuple[str, str], ...]:
    """Every `principal_id` read off a receiver that is neither derived nor a table."""
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr not in PRINCIPAL_FIELDS:
            continue
        receiver = _root_name(node.value)
        if receiver is None or receiver in _DERIVED_RECEIVERS:
            continue
        found.append((receiver, node.attr))
    return tuple(sorted(found))


def continuity_constructions(tree: ast.AST) -> tuple[tuple[int, str, str], ...]:
    """Every construction of a continuity command, with the `principal_id=` it names."""
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in CONTINUITY_COMMANDS:
            continue
        named = next(
            (kw.value for kw in node.keywords if kw.arg == "principal_id"),
            None,
        )
        rendered = "<positional or absent>" if named is None else ast.unparse(named)
        found.append((node.lineno, node.func.id, rendered))
    return tuple(found)


def _is_derived(expression: str) -> bool:
    return any(expression.endswith(chain) for chain in DERIVED_CHAINS)


def test_the_scan_reaches_the_source_tree() -> None:
    """Guards every zero below against being a walk that parsed nothing."""
    modules = _modules()
    assert len(modules) >= 100
    read_principals = [
        path for path in modules if _stated_principal_reads(ast.parse(path.read_text("utf-8")))
    ]
    assert read_principals, "no module reads a principal at all; the detector is broken"


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_no_module_reads_a_principal_from_caller_supplied_input(path: Path) -> None:
    """Claim 1: envelope, body, headers, query, path, CLI, and MCP arguments."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    reads = caller_supplied_reads(tree)
    assert reads == (), (
        f"{_relative(path)} reads a principal identity from caller-supplied "
        f"input at {[f'line {line}: {text}' for line, text in reads]}. "
        "`RequestMetadata.principal_id` and its CLI and MCP equivalents are "
        "correlation input; the acting Principal is what the composition root "
        "resolved and nothing else (MU-AC-02, specs section 8.2)"
    )


def test_the_caller_supplied_detector_reports_a_read_that_really_is_one() -> None:
    """The control for claim 1. Six shapes, because they are six different bugs."""
    bypasses = (
        "principal = metadata.principal_id",
        "principal = request.metadata.principal_id",
        "principal = body['principal_id']",
        "principal = headers.get('x')['principal_id']",
        "principal = arguments['principal_id']",
        "principal = namespace.principal_id",
    )
    for source in bypasses:
        assert caller_supplied_reads(ast.parse(source)) != (), (
            f"the detector missed {source!r}, so the zero it reports over the "
            "source tree means nothing"
        )

    # And it does not report a derived read, or every module would fail.
    for allowed in (
        "principal = authorization.principal.principal_id",
        "principal = resolved.principal_id",
        "principal = row.principal_id",
    ):
        assert caller_supplied_reads(ast.parse(allowed)) == ()


def test_reads_of_a_caller_stated_principal_match_their_registry_exactly() -> None:
    """Claim 2: a stated owner may be verified; the sites are counted."""
    measured = {
        _relative(path): reads
        for path in _modules()
        if (reads := _stated_principal_reads(ast.parse(path.read_text("utf-8"))))
    }
    assert measured == VERIFIED_CALLER_STATEMENTS, (
        "the production reads of a caller-stated `principal_id` no longer match "
        "their registry. Each registered site reads the value in order to refuse "
        "a mismatch against the server-resolved Principal; a new one has to say "
        "here what verifies it, or stop reading it"
    )


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_a_continuity_command_is_never_built_from_caller_input(path: Path) -> None:
    """Claim 3: wiring the unwired family unsafely fails here.

    Zero constructions exist today, so this passes vacuously per module — which
    is precisely why the detector is exercised against real trees below rather
    than trusted.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for lineno, command, principal in continuity_constructions(tree):
        assert _is_derived(principal), (
            f"{_relative(path)}:{lineno} builds {command} with "
            f"principal_id={principal}. A continuity command's first field is the "
            "acting Principal; it comes from the authorization that already "
            f"resolved one — an attribute chain ending in {DERIVED_CHAINS} — and "
            "never from the request"
        )


def test_the_continuity_detector_accepts_a_derived_principal_and_refuses_a_stated_one() -> None:
    """The control for claim 3, at both ends.

    `D-55`: a control that failed on every input would distinguish nothing, so
    the safe wiring has to pass the same detector the unsafe wiring fails.
    """
    unsafe = ast.parse(
        "OpenSituationCommand(principal_id=metadata.principal_id, title='t', kind='k')"
    )
    found = continuity_constructions(unsafe)
    assert len(found) == 1
    assert not _is_derived(found[0][2])

    safe = ast.parse(
        "OpenSituationCommand("
        "principal_id=authorization.principal.principal_id, title='t', kind='k')"
    )
    found = continuity_constructions(safe)
    assert len(found) == 1
    assert _is_derived(found[0][2])

    # A positional principal is refused too: it names the field without naming
    # where the value came from, and this detector cannot see through that.
    positional = ast.parse("CloseSituationCommand(caller_id, 'sit_1', 'done')")
    assert continuity_constructions(positional) == (
        (1, "CloseSituationCommand", "<positional or absent>"),
    )
    assert not _is_derived("<positional or absent>")

    # The seven names are the whole family, so a command added to
    # `application/commands.py` without being added here is not silently exempt.
    from my_pa.application import commands

    # `Command` itself is the union alias every capability's command belongs to,
    # not a member of the family.
    declared = {
        name
        for name in vars(commands)
        if name.endswith("Command") and not name.startswith("_") and name != "Command"
    }
    assert declared == CONTINUITY_COMMANDS, (
        f"the continuity command family is now {sorted(declared)}; this guard "
        "covers "
        f"{sorted(CONTINUITY_COMMANDS)}"
    )
