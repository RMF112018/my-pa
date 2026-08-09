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
   parameters, CLI namespaces, and MCP tool-argument mappings — in the
   attribute, the subscript, and the `getattr` form, under the container's own
   name *or any local name this module bound from it*. The last clause is not
   decoration: an independent review planted `context = request_metadata`
   followed by `context.principal_id`, `getattr(metadata, "principal_id")`, and
   `data = envelope.copy()` followed by `data["principal_id"]` in
   `application/service.py`, and every test in this module stayed green. All
   three are controls below now.
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

#: Every key that would constitute caller-supplied identity if it were pulled
#: out of a container a caller controls. The Entra pair joins the principal
#: names because `domain.identity.user_account.FORBIDDEN_IDENTITY_FIELDS` says
#: those three are the ones a payload must never carry, and `tid`/`oid` are what
#: a Principal is *resolved from* — a request that names them has named the
#: account the resolution would have reached.
IDENTITY_KEYS: Final = PRINCIPAL_FIELDS | frozenset({"tid", "oid"})

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
#:
#: **A name on this list is trusted for what it is bound from, not for how it is
#: spelled.** `rebound_from_caller_input` below withdraws any entry that the
#: module under inspection assigns from caller data, so `context =
#: request_metadata` followed by `context.principal_id` is a read off a
#: caller-supplied container and is reported as one. Without that, this list
#: would be a list of names an attacker may pick: `context` is the clearest case,
#: because "a PrincipalContext or an application context" is exactly the kind of
#: object a request document could be mistaken for.
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


def _bound_names(target: ast.expr) -> frozenset[str]:
    """The plain local names one assignment target binds.

    An attribute or subscript target binds nothing local — `self.x = metadata`
    rebinds a field, not a name a later expression could resolve to — so those
    return nothing rather than being mistaken for an alias.
    """
    if isinstance(target, ast.Name):
        return frozenset({target.id})
    if isinstance(target, ast.Tuple | ast.List):
        return frozenset().union(*(_bound_names(element) for element in target.elts)) or frozenset()
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return frozenset()


def _local_bindings(tree: ast.AST) -> tuple[tuple[str, ast.expr], ...]:
    """Every `name = <expression>` in `tree`, in all the forms that bind one."""
    bindings: list[tuple[str, ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                bindings.extend((name, node.value) for name in _bound_names(target))
        elif (
            isinstance(node, ast.AnnAssign | ast.AugAssign | ast.NamedExpr)
            and node.value is not None
        ):
            bindings.extend((name, node.value) for name in _bound_names(node.target))
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            bindings.extend((name, node.context_expr) for name in _bound_names(node.optional_vars))
        elif isinstance(node, ast.For | ast.AsyncFor):
            bindings.extend((name, node.iter) for name in _bound_names(node.target))
    return tuple(bindings)


def _chain_root(node: ast.expr) -> str | None:
    """The name an attribute/subscript/call chain is *rooted at*, or `None`.

    The deepest name rather than the nearest one, which is the opposite end of
    the chain from `_root_name`: `envelope.copy()` is rooted at `envelope`, and
    that is the fact that decides whether the result is caller data.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute | ast.Subscript):
        return _chain_root(node.value)
    if isinstance(node, ast.Call):
        return _chain_root(node.func)
    if isinstance(node, ast.Await | ast.Starred):
        return _chain_root(node.value)
    return None


def rebound_from_caller_input(tree: ast.AST) -> frozenset[str]:
    """Local names bound, directly or transitively, from a caller-supplied container.

    This is what makes `CALLER_SUPPLIED` a statement about objects rather than
    about spelling. `context = request_metadata` puts `context` here, and
    `data = envelope.copy()` puts `data` here, so neither the whitelist below nor
    a freshly invented neutral name launders the read that follows.

    Transitive and to a fixed point, because one rename is as good as two:
    `first = metadata`, `second = first`, `second.principal_id` is the same
    defect written across three lines.

    Propagation is by the **root of the assigned chain**, not by whether a
    caller-supplied name appears anywhere in the expression, and the difference
    is the whole of what keeps this from being useless. `authorization =
    self._authorize(..., metadata, ...)` mentions `metadata` and returns the
    resolved `Authorization` — treating that as caller data would report every
    correct use case in the tree and the guard would have to be turned off. A
    chain rooted at a caller-supplied name is a *reference into* the caller's
    document; a call that merely takes one is a derivation, and the second
    detector's exact registry is what covers a derivation whose result is then
    read as a principal.

    Public for the same reason `caller_supplied_reads` is: a control below runs
    it over trees that really do rebind, so the empty answer it gives for
    production is a measurement.
    """
    bindings = _local_bindings(tree)
    rebound: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, value in bindings:
            if name in rebound or name in CALLER_SUPPLIED:
                continue
            if _chain_root(value) in (CALLER_SUPPLIED | rebound):
                rebound.add(name)
                changed = True
    return frozenset(rebound)


def identity_read(node: ast.AST, keys: frozenset[str]) -> tuple[ast.expr, str] | None:
    """The container and key of one identity read, in each of the three forms.

    `x.principal_id`, `x["principal_id"]`, and `getattr(x, "principal_id")` are
    one defect written three ways, and a detector that walked only the first was
    a detector two rewrites got past. `getattr` with a computed name is not here
    on purpose: `getattr(parsed, field)` in the CLI adapter iterates a list of
    option names, and reporting it would say nothing about identity.
    """
    if isinstance(node, ast.Attribute) and node.attr in keys:
        return node.value, node.attr
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
        and node.slice.value in keys
    ):
        return node.value, node.slice.value
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
        and node.args[1].value in keys
    ):
        return node.args[0], node.args[1].value
    return None


def caller_supplied_reads(tree: ast.AST) -> tuple[tuple[int, str], ...]:
    """Every identity read off a caller-supplied container in `tree`.

    Public, because this module's own control runs it over a synthetic tree that
    really does contain one. A detector that found nothing would otherwise agree
    with the production zero for the wrong reason.

    Three axes, each of which was a way past the first version of this function:
    the *key* is any of `IDENTITY_KEYS` rather than the principal names alone,
    the *form* is attribute, subscript, or `getattr`, and the *container* is
    anything `CALLER_SUPPLIED` names **or anything this module bound from one**.
    """
    untrusted = CALLER_SUPPLIED | rebound_from_caller_input(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        read = identity_read(node, IDENTITY_KEYS)
        if read is None:
            continue
        container, _ = read
        if _chain_names(container) & untrusted:
            found.append((node.lineno, ast.unparse(node)))  # type: ignore[attr-defined]
    return tuple(sorted(found))


def _stated_principal_reads(tree: ast.AST) -> tuple[tuple[str, str], ...]:
    """Every `principal_id` read off a receiver that is neither derived nor a table.

    The backstop behind claim 1: whatever `caller_supplied_reads` does not
    classify as caller data still has to be a receiver someone registered. It
    reads the same three forms, so a subscript is not a blind spot here either,
    and it withdraws `_DERIVED_RECEIVERS` membership from any name this module
    rebound from caller input — a whitelisted name that was assigned a request
    document is not a derived receiver, whatever it is called.
    """
    derived = _DERIVED_RECEIVERS - rebound_from_caller_input(tree)
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        read = identity_read(node, PRINCIPAL_FIELDS)
        if read is None:
            continue
        container, field = read
        receiver = _root_name(container)
        if receiver is None or receiver in derived:
            continue
        found.append((receiver, field))
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
    """The control for claim 1. Each shape is a different bug, not a restatement.

    The last three were each a **reachable bypass** of the first version of this
    guard: all three were planted in `application/service.py` and the whole
    module stayed green. They are kept here in the exact form that got through,
    because the value of a control is that it fails on what the thing it controls
    used to miss.
    """
    bypasses = (
        "principal = metadata.principal_id",
        "principal = request.metadata.principal_id",
        "principal = body['principal_id']",
        "principal = headers.get('x')['principal_id']",
        "principal = arguments['principal_id']",
        "principal = namespace.principal_id",
        # Aliasing onto a whitelisted receiver name. `context` is trusted for
        # being a `PrincipalContext`, and an application context is exactly what
        # a request document could be mistaken for.
        "context = request_metadata\nprincipal = context.principal_id",
        # The same read, through the builtin rather than the syntax.
        "principal = getattr(metadata, 'principal_id')",
        # Subscript off a neutral name. There was no backstop at all for this
        # one: the detector walked `ast.Attribute` and never `ast.Subscript`
        # through a rebound name.
        "data = envelope.copy()\nprincipal = data['principal_id']",
        # Two renames are one rename twice.
        "first = metadata\nsecond = first\nprincipal = second.principal_id",
        # The Entra pair is identity too: a payload that names `tid`/`oid` has
        # named the account the resolution would have reached.
        "claims = payload['claims']\ntenant = claims['tid']",
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
        # `D-55` again, and the reason the alias rule propagates by the *root*
        # of the assigned chain rather than by any mention: a use case binds its
        # `Authorization` from a call that takes the request document, and that
        # is the correct shape. A rule that reported this would report every
        # handler in the tree, and a guard that fires on everything is a guard
        # somebody switches off.
        "authorization = self._authorize(metadata, command)\n"
        "principal = authorization.principal.principal_id",
        # A computed attribute name says nothing about identity: the CLI adapter
        # iterates its own option names through `getattr(parsed, field)`.
        "for field in fields:\n    supplied = getattr(parsed, field)",
    ):
        assert caller_supplied_reads(ast.parse(allowed)) == (), (
            f"the detector reported {allowed!r}, which is a derived read; a "
            "control that failed on every input would distinguish nothing"
        )


def test_the_alias_rule_withdraws_a_whitelisted_name_that_was_rebound() -> None:
    """`_DERIVED_RECEIVERS` is trusted for what a name is bound from, not its spelling.

    The claim-2 backstop is the other half of the alias fix. If `context` stayed
    whitelisted after being assigned a request document, a rebound read would be
    invisible to *both* detectors rather than one, and the exact registry below
    would go on agreeing with a tree that had a hole in it.
    """
    rebound = ast.parse("context = request_metadata\nprincipal = context.principal_id")
    # `principal` is rebound too, and that is the rule working rather than
    # leaking: a name bound from a rebound one carries the same taint, so
    # `principal` stops being a derived receiver in this tree as well.
    assert rebound_from_caller_input(rebound) == frozenset({"context", "principal"})
    assert _stated_principal_reads(rebound) == (("context", "principal_id"),)

    # The control at the other end: an untouched `context` stays derived, or
    # every module that carries a `PrincipalContext` would land in the registry.
    intact = ast.parse(
        "context = capture_context(principal.principal_id)\nx = context.principal_id"
    )
    assert rebound_from_caller_input(intact) == frozenset()
    assert _stated_principal_reads(intact) == ()

    # And the subscript and `getattr` forms reach the backstop too, so the
    # registry is exact over all three ways of writing the same read.
    assert _stated_principal_reads(ast.parse("x = found['principal_id']")) == (
        ("found", "principal_id"),
    )
    assert _stated_principal_reads(ast.parse("x = getattr(found, 'principal_id')")) == (
        ("found", "principal_id"),
    )


def test_the_identity_keys_are_the_ones_the_domain_forbids_in_a_payload() -> None:
    """`tid` and `oid` are in `IDENTITY_KEYS` because the domain says they are.

    Bound to `domain.identity.user_account.FORBIDDEN_IDENTITY_FIELDS` rather than
    restated, so a fourth forbidden key added there cannot leave this scan
    checking three.
    """
    from my_pa.domain.identity.user_account import FORBIDDEN_IDENTITY_FIELDS

    assert FORBIDDEN_IDENTITY_FIELDS <= IDENTITY_KEYS, (
        f"{sorted(FORBIDDEN_IDENTITY_FIELDS - IDENTITY_KEYS)} are forbidden in a "
        "payload by the domain and are not scanned for here"
    )


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
