"""WP-RE-08 G-A02-1 (RE-AC-103, Amendment 02 (1), MR-10): the staged principal is durable.

Every Record Event's `principal_id` must derive from the composition root's
authenticated durable Principal -- `authorization.principal.principal_id` -- or a
registered stored-partition root, and never from a request, an argument, or a
per-process or random mint. The one enumerated exception (MR-10) is the legacy
import CLI's `--principal`, and only in `apps/cli/tbr_import.py`, where the CLI
itself refuses anything but the durable bound form
(`tests/unit/test_tbr_import_principal_shape.py`).

Two FAST claims, read with `ast` over `src/` and `apps/`:

1. **Mint registry.** Every `capture_principal_id(...)`, `Principal(...)` and
   `PrincipalContext(...)` construction is a registered site with a registered
   argument; there is no `issue_identifier(IdKind.PRINCIPAL)` at all, and no
   registered argument draws on `uuid1`/`uuid4`, `secrets` or `random`.
2. **Staging provenance.** For every call that builds a draft
   (`RecordEventDraft.issue`, `RecordEventDraft(...)`, and every function
   annotated `-> RecordEventDraft`), the `principal_id=` expression is traced
   back: through local assignments, enclosing-function closures, attribute hops
   on request objects (`request.principal_id` -> the `principal_id=` its
   construction passed), `dataclasses.replace`, and parameters -> each
   production caller's argument, resolved by name and signature compatibility,
   at most `MAX_CALLER_HOPS` hops. Every path must end at a root. A parameter
   with no production caller must be listed in `UNCALLED_ENTRIES`; a caller the
   name-and-signature resolution attributes wrongly must be listed in
   `NOT_A_CALLER`. Both lists are explicit so that ambiguity is visible, never
   silent.

It complements `test_principal_is_never_caller_supplied.py` (no read from caller
containers) with the positive claim: where the staged value comes from.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]

#: The composition root's authenticated durable Principal, as every request
#: handler reads it off the server-resolved `Authorization`.
AUTHORIZATION_ROOT: Final = "authorization.principal.principal_id"
#: W5: the stored partition of a registered re-enrichment work row, written at
#: registration from an Authorization.
STORED_ROOTS: Final = frozenset({"work_partition(connection, work.work_id)"})
#: MR-10: the ONE enumerated argument-supplied root, named by path.
ARGUMENT_ROOT: Final = ("apps/cli/tbr_import.py", "args.principal")

#: The review-promotion path (`review.decide` -> entity proposal review ->
#: promotion -> `resolve_mention` -> `entity_record_event`) is seven hops deep.
MAX_CALLER_HOPS: Final = 8

#: Public `TaskManagementService` conveniences no production path calls; their
#: `principal_id` can only come from a direct in-process caller.
UNCALLED_ENTRIES: Final = frozenset(
    {
        ("src/my_pa/application/tasks.py", "archive"),
        ("src/my_pa/application/tasks.py", "defer"),
        ("src/my_pa/application/tasks.py", "link_commitment"),
        ("src/my_pa/application/tasks.py", "schedule"),
        ("src/my_pa/application/tasks.py", "set_priority"),
        ("src/my_pa/application/tasks.py", "set_role"),
        ("src/my_pa/application/tasks.py", "unarchive"),
        ("src/my_pa/application/tasks.py", "update_description"),
        ("src/my_pa/application/tasks.py", "update_title"),
    }
)

#: Calls the name-and-signature resolution would attribute to a staging
#: function but that reach a different method of the same name: (caller path,
#: called name, receiver text).
NOT_A_CALLER: Final = frozenset(
    {
        # `MeetingRepository.update_meeting`, not `MeetingApplication.update_meeting`.
        ("src/my_pa/application/meetings.py", "update_meeting", "meetings"),
    }
)

#: Claim 1: every principal construction, by (path, callee, argument).
MINT_SITES: Final = frozenset(
    {
        (
            "src/my_pa/application/goodnotes_gsqs_b0_stdio_session.py",
            "capture_principal_id",
            "LOCAL_OPERATOR_UUID",
        ),
        (
            "src/my_pa/bootstrap/apple_machine_control.py",
            "Principal",
            "identity.principal_id",
        ),
        (
            "src/my_pa/bootstrap/gateway.py",
            "Principal",
            "capture_principal_id(LOCAL_OPERATOR_UUID)",
        ),
        ("src/my_pa/bootstrap/gateway.py", "capture_principal_id", "LOCAL_OPERATOR_UUID"),
        (
            "src/my_pa/bootstrap/gateway.py",
            "Principal",
            "capture_principal_id(authenticated.account.principal_id)",
        ),
        (
            "src/my_pa/bootstrap/gateway.py",
            "capture_principal_id",
            "authenticated.account.principal_id",
        ),
        ("src/my_pa/bootstrap/gateway.py", "Principal", "client.principal_id"),
        ("src/my_pa/bootstrap/settings.py", "capture_principal_id", "LOCAL_OPERATOR_UUID"),
        (
            "src/my_pa/infrastructure/persistence/principal_scope.py",
            "PrincipalContext",
            "durable_principal_uuid(principal_id)",
        ),
        (
            "src/my_pa/infrastructure/security/gsqs_remote_eval_authentication.py",
            "capture_principal_id",
            "LOCAL_OPERATOR_UUID",
        ),
        (
            "src/my_pa/infrastructure/security/principal_identity.py",
            "PrincipalContext",
            "account.principal_id",
        ),
        (
            "src/my_pa/infrastructure/security/remote_oauth.py",
            "capture_principal_id",
            "resolved.principal_id",
        ),
        ("src/my_pa/infrastructure/security/remote_oauth.py", "Principal", "principal_id"),
        ("apps/apple_grant.py", "Principal", "principal_id"),
        ("apps/cli/gsqs_b0.py", "Principal", "capture_principal_id(LOCAL_OPERATOR_UUID)"),
        ("apps/cli/gsqs_b0.py", "capture_principal_id", "LOCAL_OPERATOR_UUID"),
    }
)
MINT_CALLEES: Final = frozenset({"capture_principal_id", "Principal", "PrincipalContext"})
ENTROPY: Final = frozenset({"uuid1", "uuid4", "secrets", "random", "token_hex", "token_urlsafe"})


# ---- the index ------------------------------------------------------------------


@dataclass(eq=False)
class Function:
    path: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    owner: str | None
    parent: Function | None


@dataclass
class Index:
    """Every function and call in the scanned sources, and the draft builders."""

    functions: list[Function] = field(default_factory=list)
    calls: dict[str, list[tuple[str, Function, ast.Call]]] = field(default_factory=dict)
    trees: dict[str, ast.Module] = field(default_factory=dict)

    @classmethod
    def of(cls, sources: dict[str, str]) -> Index:
        index = cls()
        for path, source in sorted(sources.items()):
            tree = ast.parse(source)
            index.trees[path] = tree
            index._walk(path, tree, None, None)
        return index

    def _walk(self, path: str, node: ast.AST, owner: str | None, function: Function | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                self._walk(path, child, child.name, function)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = Function(path, child, owner, function)
                self.functions.append(inner)
                self._walk(path, child, owner, inner)
            else:
                if isinstance(child, ast.Call) and function is not None:
                    name = _called(child)
                    if name is not None:
                        self.calls.setdefault(name, []).append((path, function, child))
                self._walk(path, child, owner, function)

    def named(self, name: str) -> list[Function]:
        return [function for function in self.functions if function.node.name == name]

    @property
    def builders(self) -> frozenset[str]:
        return frozenset(
            function.node.name
            for function in self.functions
            if function.node.returns is not None
            and "RecordEventDraft" in ast.unparse(function.node.returns)
            and function.node.name != "issue"
        )


def _called(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _positional(function: Function) -> list[str]:
    arguments = function.node.args
    names = [argument.arg for argument in arguments.posonlyargs + arguments.args]
    return names[1:] if names and names[0] in {"self", "cls"} else names


def _compatible(call: ast.Call, function: Function) -> bool:
    """Could `call` bind to `function`? Positional count, keywords, required keywords."""
    arguments = function.node.args
    plain = [argument for argument in call.args if not isinstance(argument, ast.Starred)]
    if arguments.vararg is None and len(plain) > len(_positional(function)):
        return False
    if any(isinstance(argument, ast.Starred) for argument in call.args) or any(
        keyword.arg is None for keyword in call.keywords
    ):
        return True
    names = {a.arg for a in arguments.posonlyargs + arguments.args + arguments.kwonlyargs}
    if arguments.kwarg is None and any(keyword.arg not in names for keyword in call.keywords):
        return False
    required = {
        argument.arg
        for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
        if default is None
    }
    return required <= {keyword.arg for keyword in call.keywords}


def _targets(index: Index, path: str, caller: Function, call: ast.Call) -> list[Function]:
    name = _called(call)
    candidates = index.named(name or "")
    if len(candidates) <= 1:
        return candidates
    if isinstance(call.func, ast.Name):
        local = [f for f in candidates if f.path == path and f.owner is None]
        return local or [f for f in candidates if f.owner is None and _compatible(call, f)]
    receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
    if isinstance(receiver, ast.Name) and receiver.id in {"self", "cls"}:
        own = [f for f in candidates if f.path == path and f.owner == caller.owner]
        if own:
            return own
    return [f for f in candidates if f.owner is not None and _compatible(call, f)]


def _argument(call: ast.Call, function: Function, parameter: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == parameter:
            return keyword.value
    positional = _positional(function)
    if parameter in positional:
        at = positional.index(parameter)
        head = call.args[: at + 1]
        if len(call.args) > at and not any(isinstance(a, ast.Starred) for a in head):
            return call.args[at]
    return None


def _assigned(function: Function, name: str) -> list[ast.expr]:
    found: list[ast.expr] = []
    for node in ast.walk(function.node):
        if isinstance(node, ast.Assign):
            found.extend(
                node.value
                for target in node.targets
                if isinstance(target, ast.Name) and target.id == name
            )
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            found.append(node.value)
    return found


def _is_parameter(function: Function, name: str) -> bool:
    arguments = function.node.args
    every = arguments.posonlyargs + arguments.args + arguments.kwonlyargs
    return any(argument.arg == name for argument in every)


# ---- the trace ------------------------------------------------------------------


@dataclass
class Trace:
    """The outcome of tracing every staging site's `principal_id`."""

    index: Index
    failures: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    uncalled: set[tuple[str, str]] = field(default_factory=set)
    argument_roots: set[tuple[str, str]] = field(default_factory=set)
    sites: int = 0
    _active: set[tuple[int, str, str | None]] = field(default_factory=set)
    _memo: dict[tuple[int, str, str | None], bool] = field(default_factory=dict)

    def run(self) -> Trace:
        builders = self.index.builders
        for name, calls in self.index.calls.items():
            for path, function, call in calls:
                full = ast.unparse(call.func)
                if full not in {"RecordEventDraft.issue", "RecordEventDraft"} and (
                    name not in builders
                ):
                    continue
                for keyword in call.keywords:
                    if keyword.arg == "principal_id":
                        self.sites += 1
                        self.expression(keyword.value, function, 0, (f"{path}:{call.lineno}",))
        return self

    def fail(self, reason: str, chain: tuple[str, ...]) -> bool:
        self.failures.append((reason, chain))
        return False

    def expression(
        self,
        expr: ast.expr,
        function: Function,
        hops: int,
        chain: tuple[str, ...],
        attribute: str | None = None,
    ) -> bool:
        text = ast.unparse(expr)
        chain = (*chain, f"{function.path}:{function.node.name}:{text}:{attribute or ''}")
        if attribute is None and (text == AUTHORIZATION_ROOT or text in STORED_ROOTS):
            return True
        if attribute is None and (function.path, text) == ARGUMENT_ROOT:
            self.argument_roots.add(ARGUMENT_ROOT)
            return True
        if hops > MAX_CALLER_HOPS:
            return self.fail("too many caller hops", chain)
        if (
            attribute is None
            and isinstance(expr, ast.Attribute)
            and expr.attr == "principal_id"
            and not (isinstance(expr.value, ast.Name) and expr.value.id == "self")
        ):
            return self.expression(expr.value, function, hops, chain, "principal_id")
        if isinstance(expr, ast.Call):
            if attribute is None:
                return self.fail("a call is not a principal source", chain)
            for keyword in expr.keywords:
                if keyword.arg == attribute:
                    return self.expression(keyword.value, function, hops, chain)
            if ast.unparse(expr.func) in {"replace", "dataclasses.replace"} and expr.args:
                return self.expression(expr.args[0], function, hops, chain, attribute)
            return self.fail("a construction that names no principal", chain)
        if isinstance(expr, ast.Name):
            return self.name(expr, function, hops, chain, attribute)
        return self.fail("not a principal source", chain)

    def name(
        self,
        expr: ast.Name,
        function: Function,
        hops: int,
        chain: tuple[str, ...],
        attribute: str | None,
    ) -> bool:
        mark = (id(function), expr.id, attribute)
        if mark in self._active:
            return True  # a cycle (`record = replace(record, ...)`) adds no new source
        self._active.add(mark)
        try:
            values = _assigned(function, expr.id)
            # Every assignment is traced (no short-circuit), so every failure is listed.
            results = [self.expression(v, function, hops, chain, attribute) for v in values]
            ok = all(results)
            if _is_parameter(function, expr.id):
                return self.parameter(expr.id, function, hops, chain, attribute) and ok
            if values:
                return ok
        finally:
            self._active.discard(mark)
        if function.parent is not None:
            return self.name(expr, function.parent, hops, chain, attribute)
        return self.fail("an unbound name", chain)

    def parameter(
        self,
        parameter: str,
        function: Function,
        hops: int,
        chain: tuple[str, ...],
        attribute: str | None,
    ) -> bool:
        key = (id(function), parameter, attribute)
        if key in self._memo:
            return self._memo[key]
        self._memo[key] = True
        ok, found = True, 0
        for path, caller, call in self.index.calls.get(function.node.name, []):
            receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
            excluded = (path, function.node.name, ast.unparse(receiver) if receiver else "")
            if excluded in NOT_A_CALLER:
                continue
            if function not in _targets(self.index, path, caller, call):
                continue
            argument = _argument(call, function, parameter)
            if argument is None:
                continue
            found += 1
            ok = self.expression(argument, caller, hops + 1, chain, attribute) and ok
        if found == 0:
            if attribute is None and parameter == "principal_id":
                self.uncalled.add((function.path, function.node.name))
            else:
                ok = self.fail("a parameter no production caller supplies", chain)
        self._memo[key] = ok
        return ok


def _sources(extra: dict[str, str] | None = None) -> dict[str, str]:
    sources = {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
        for root in ("src", "apps")
        for path in sorted((ROOT / root).rglob("*.py"))
    }
    sources.update(extra or {})
    return sources


def _mints(index: Index) -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for name, calls in index.calls.items():
        for path, _function, call in calls:
            if (
                name == "issue_identifier"
                and call.args
                and ast.unparse(call.args[0]) == "IdKind.PRINCIPAL"
            ):
                found.add((path, name, "IdKind.PRINCIPAL"))
            if name not in MINT_CALLEES:
                continue
            argument = next(
                (k.value for k in call.keywords if k.arg == "principal_id"),
                call.args[0] if call.args else None,
            )
            found.add((path, name, "" if argument is None else ast.unparse(argument)))
    return found


# ---- claim 1: the mint registry --------------------------------------------------


def test_the_principal_mint_sites_are_exactly_the_registered_ones() -> None:
    assert _mints(Index.of(_sources())) == MINT_SITES


def test_no_principal_is_ever_issued_or_drawn_from_entropy() -> None:
    found = _mints(Index.of(_sources()))
    assert not {site for site in found if site[1] == "issue_identifier"}
    for _path, _callee, argument in found:
        assert not any(word in argument for word in ENTROPY), argument


# ---- claim 2: staging provenance --------------------------------------------------


def test_every_staged_principal_derives_from_the_durable_principal() -> None:
    trace = Trace(Index.of(_sources())).run()
    assert trace.sites >= 30, "the scan found too few staging sites to prove anything"
    assert trace.failures == [], "\n".join(
        f"{reason}: " + " <- ".join(chain) for reason, chain in trace.failures
    )
    assert trace.uncalled == UNCALLED_ENTRIES


def test_the_legacy_import_is_the_one_argument_root() -> None:
    """MR-10: the exception is named by path, and it is actually reached."""
    trace = Trace(Index.of(_sources())).run()
    assert trace.argument_roots == {ARGUMENT_ROOT}


# ---- controls: the trace reports what it must -------------------------------------

_PLANTED_BUILDER: Final = (
    "def handler(self, unit_of_work, authorization, command, metadata):\n"
    "    unit_of_work.record_events.stage(RecordEventDraft.issue(principal_id={value}))\n"
)


def _planted_failures(extra: dict[str, str]) -> list[str]:
    trace = Trace(Index.of(_sources(extra))).run()
    return [" <- ".join(chain) for _reason, chain in trace.failures]


def test_a_request_supplied_principal_is_reported() -> None:
    for value in ("command.principal_id", "metadata.principal_id", "command.idempotency_key"):
        failures = _planted_failures({"src/my_pa/planted.py": _PLANTED_BUILDER.format(value=value)})
        assert any("src/my_pa/planted.py" in failure for failure in failures), value


def test_a_per_process_or_random_mint_is_reported() -> None:
    for value in ("capture_principal_id(uuid4())", "issue_identifier(IdKind.PRINCIPAL)"):
        failures = _planted_failures({"src/my_pa/planted.py": _PLANTED_BUILDER.format(value=value)})
        assert any("src/my_pa/planted.py" in failure for failure in failures), value


def test_an_argument_principal_outside_the_legacy_import_is_reported() -> None:
    planted = {
        "apps/cli/planted.py": (
            "def main(args):\n    PlantedService().record(principal_id=args.principal)\n"
        ),
        "src/my_pa/planted_service.py": (
            "class PlantedService:\n"
            "    def record(self, *, principal_id):\n"
            "        RecordEventDraft.issue(principal_id=principal_id)\n"
        ),
    }
    failures = _planted_failures(planted)
    assert any("apps/cli/planted.py" in failure for failure in failures)


def test_a_new_argument_mint_changes_the_registry() -> None:
    planted = {"src/my_pa/planted.py": "def f(args):\n    return Principal(args.principal)\n"}
    assert _mints(Index.of(_sources(planted))) != MINT_SITES
