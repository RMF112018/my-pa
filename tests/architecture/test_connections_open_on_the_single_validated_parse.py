"""Every production connection opens on the parse validation made, not on the string.

`Settings` states a guarantee its callers rely on: `database_url` is read once,
by `make_url`, during validation, and the `URL` that reading produced is the
object handed to `create_database_engine`. `create_engine` returns a `URL`
unchanged rather than parsing it again, so passing the parse is what leaves no
second reading of the text to diverge from the first. Passing `database_url` —
the raw string — re-enters the parser, and a string two parsers can read two
ways is a string whose approved host and whose connected host need not be the
same one.

That guarantee was stated in prose, in `parsed_database_url`'s docstring ("Pass
this, not `database_url`, to anything that opens a connection"), and prose is
what let it be measured at one call site in seven. Reverting the six non-gateway
callers to `.database_url` reddened nothing: only `bootstrap/gateway.py` had a
test that named the parse. This is the control that prose was not.

The rule is stated once, here, and derived from each module's own syntax tree
rather than from a list of call sites a reviewer would have to keep current:

    in a production module, the URL argument of every `create_database_engine`
    call resolves to a `.parsed_database_url()` call.

"Resolves to" and not "is", because the argument is not always written at the
call. `migrations/env.py` binds the parse to a module-level name and passes the
name, and — the trap a name-based scan walks into — that name is spelled
`database_url`. So provenance is followed through local bindings, and the
classification is made on the *shape of the expression the name was bound to*:
an attribute read of `database_url` is raw wherever it appears, a call of
`parsed_database_url` is the parse wherever it appears, and a name is whatever
it was assigned. Anything else — a literal, a parameter, a function return the
scan cannot see through — is `unknown`, and `unknown` fails. A connection-opener
in production has no business sourcing its URL from somewhere this scan cannot
name, and failing closed is the only reading under which a future caller has to
argue its case rather than slip past a whitelist.

**Scope, and why the tests tree is outside it.** `tests/` and its fixtures open
connections on disposable databases they create and drop themselves — a URL
built by a fixture, or a literal pointing at a host that does not resolve. Those
are legitimate and they are exactly the shapes this scan calls `unknown`, so
including the tests tree would make the guard fire on the one population it must
not. The exclusion is not incidental and
`test_the_tests_tree_is_deliberately_out_of_scope` holds it to that: it asserts
that the tests tree really does contain callers this rule would reject, so the
exclusion stays a decision somebody made rather than a root nobody added.

**What this does not prove.** Nothing behavioural. It does not show that the
`URL` reaching `create_engine` is the same object validation approved — that is
`tests/unit/test_settings.py`'s identity assertion — nor that the gateway
composes two engines from it, which is `tests/unit/test_gateway_composition.py`.
It shows only that no production module *asks* for the second parse. Two
syntactic limits, named rather than left to be found: provenance is followed
through assignments to plain names, so a URL reached through a container, an
attribute of a local object, or a rebinding inside a comprehension is `unknown`
rather than traced (it fails, which is the safe direction); and a name assigned
in two places is raw if either assignment is raw, which is a conservative merge
and not a flow-sensitive one.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Literal

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: The trees that run in production. `tests` and `fixtures` are deliberately
#: absent; see the module docstring and the test that holds the exclusion.
PRODUCTION_ROOTS: tuple[str, ...] = ("src", "apps", "scripts", "migrations")

#: The factory that opens a pool. Matched by name rather than by resolved
#: import, because a module that aliases it on import has still called it.
ENGINE_FACTORY = "create_database_engine"

#: The accessor that returns the single parse validation made.
PARSE_ACCESSOR = "parsed_database_url"

#: The raw field. Reading it is not itself wrong — `Settings` has to store the
#: string somewhere — but handing it to the factory is.
RAW_FIELD = "database_url"

#: The keyword `create_database_engine` names its URL parameter, for a caller
#: that passes it by keyword instead of positionally.
URL_KEYWORD = "url"

Provenance = Literal["parse", "raw", "unknown"]


def _bindings(tree: ast.AST) -> dict[str, list[ast.expr]]:
    """Every expression assigned to a plain name anywhere in `tree`.

    Scope-insensitive on purpose. A scan that tracked scopes would have to model
    closures and globals to say anything useful about `migrations/env.py`, where
    the binding is at module level and the use is inside a function; merging all
    bindings for a name is the conservative reading, because a name assigned the
    raw string anywhere is treated as raw at every use of it.
    """
    bound: dict[str, list[ast.expr]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [target for target in node.targets if isinstance(target, ast.Name)]
            for target in targets:
                bound.setdefault(target.id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                bound.setdefault(node.target.id, []).append(node.value)
    return bound


def _provenance(
    node: ast.expr, bindings: dict[str, list[ast.expr]], seen: frozenset[str] = frozenset()
) -> Provenance:
    """Where the URL this expression evaluates to came from.

    `parse` only for a call of `parsed_database_url` — the accessor that hands
    back the object validation built. `raw` for any attribute read of
    `database_url`, whatever the receiver is spelled, because
    `settings.database_url` and `load_settings().database_url` are the same
    mistake. Everything else is `unknown` and `unknown` fails.
    """
    if isinstance(node, ast.Call):
        callee = node.func
        if isinstance(callee, ast.Attribute) and callee.attr == PARSE_ACCESSOR:
            return "parse"
        return "unknown"
    if isinstance(node, ast.Attribute):
        return "raw" if node.attr == RAW_FIELD else "unknown"
    if isinstance(node, ast.Name):
        if node.id in seen:
            # A cycle (`url = url`). Unresolvable, so it fails closed.
            return "unknown"
        assigned = bindings.get(node.id)
        if not assigned:
            return "unknown"
        resolved = [_provenance(value, bindings, seen | {node.id}) for value in assigned]
        if "raw" in resolved:
            return "raw"
        return "parse" if all(item == "parse" for item in resolved) else "unknown"
    return "unknown"


def _url_argument(call: ast.Call) -> ast.expr | None:
    """The expression `create_database_engine` will read its URL from."""
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg == URL_KEYWORD:
            return keyword.value
    return None


def _factory_calls(tree: ast.AST) -> list[ast.Call]:
    """Every call of the engine factory, however the name was reached."""
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        named = isinstance(callee, ast.Name) and callee.id == ENGINE_FACTORY
        attributed = isinstance(callee, ast.Attribute) and callee.attr == ENGINE_FACTORY
        if named or attributed:
            found.append(node)
    return found


def unvalidated_connections(source: str, filename: str) -> list[str]:
    """Every engine this source opens on something other than the stored parse.

    Reported as `line:provenance`, so a failure names the call rather than only
    the file, and distinguishes the defect this closes (`raw`) from a URL the
    scan cannot account for (`unknown`).
    """
    tree = ast.parse(source, filename=filename)
    bindings = _bindings(tree)
    offending: list[str] = []
    for call in _factory_calls(tree):
        argument = _url_argument(call)
        if argument is None:
            offending.append(f"{call.lineno}:missing")
            continue
        provenance = _provenance(argument, bindings)
        if provenance != "parse":
            offending.append(f"{call.lineno}:{provenance}")
    return sorted(offending)


def _production_modules() -> list[Path]:
    return sorted(
        path
        for root in PRODUCTION_ROOTS
        for path in (ROOT / root).rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _opens_connections(path: Path) -> bool:
    """Whether this module calls the engine factory at all."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return bool(_factory_calls(tree))


CONNECTION_OPENERS: list[Path] = [
    path for path in _production_modules() if _opens_connections(path)
]


def test_the_scan_reaches_the_production_connection_openers() -> None:
    """Non-vacuity for the tree, not for the rule.

    Derived rather than asserted against a count: every production module that
    calls the factory is collected, and the set has to be non-trivial. A scan
    that stopped matching — because the factory was renamed, or a root moved —
    would empty this and fail here rather than pass the rule silently.
    """
    assert CONNECTION_OPENERS, "no production module calls the engine factory; the scan is blind"
    roots = {path.relative_to(ROOT).parts[0] for path in CONNECTION_OPENERS}
    assert roots <= set(PRODUCTION_ROOTS)
    assert len(CONNECTION_OPENERS) >= 2


@pytest.mark.parametrize("path", CONNECTION_OPENERS, ids=lambda p: str(Path(p).relative_to(ROOT)))
def test_no_production_module_opens_a_connection_on_the_raw_url(path: Path) -> None:
    """The rule, applied to every module that opens a connection.

    This fails with `raw` on any caller reverted to `settings.database_url`,
    which is the state six of the seven were in before this guard existed.
    """
    offending = unvalidated_connections(path.read_text(encoding="utf-8"), str(path))
    assert offending == [], (
        f"{path.relative_to(ROOT)}: engine opened on a URL that is not the stored parse "
        f"at {offending}; pass Settings.parsed_database_url(), not Settings.database_url"
    )


#: A module shaped like a connection-opening caller and nothing more. Written
#: out rather than cut from a real file, so the control states the rule instead
#: of copying today's implementation. The URL is obviously synthetic and points
#: at a host that does not resolve.
PLANTED = """\
from my_pa.bootstrap.settings import load_settings
from my_pa.infrastructure.database.engine import create_database_engine

{binding}


def build():
    return create_database_engine({argument})
"""

CASES: tuple[tuple[str, str, str, list[str]], ...] = (
    # The defect this closes: the raw field handed straight to the factory.
    ("the raw field", "", "load_settings().database_url", ["8:raw"]),
    # The same defect one hop away, which a call-site-only scan would miss.
    ("the raw field through a name", "chosen = load_settings().database_url", "chosen", ["8:raw"]),
    # The trap for a name-based scan: the binding is *named* `database_url` and
    # holds the parse. This is `migrations/env.py`'s shape and it is correct.
    (
        "the parse bound to a name spelled like the field",
        "database_url = load_settings().parsed_database_url()",
        "database_url",
        [],
    ),
    # The shape every caller must have.
    ("the parse at the call", "", "load_settings().parsed_database_url()", []),
    # By keyword rather than positionally: the same read, still raw.
    ("the raw field by keyword", "", "url=load_settings().database_url", ["8:raw"]),
    # A URL that never went through validation at all. Not the defect this
    # closes, but not something a production opener may do either.
    (
        "a literal that bypassed validation",
        "",
        '"postgresql+psycopg://synthetic@nowhere.invalid/synthetic"',
        ["8:unknown"],
    ),
)


@pytest.mark.parametrize(
    ("name", "binding", "argument", "expected"), CASES, ids=[case[0] for case in CASES]
)
def test_the_scan_discriminates(
    name: str, binding: str, argument: str, expected: list[str]
) -> None:
    """Non-vacuity for the rule, and its paired control.

    A scan that reported everything would pass the rule above the day it broke,
    and a scan that reported nothing would pass it for ever. The same planted
    module is run six ways: three that must be rejected, three that must be
    accepted, and one of the accepted three is the alias whose *name* is the
    raw field — so the scan is answering the question rather than its own name.
    """
    offending = unvalidated_connections(
        PLANTED.format(binding=binding, argument=argument), f"<planted: {name}>"
    )
    assert offending == expected


def test_the_tests_tree_is_deliberately_out_of_scope() -> None:
    """The exclusion is a decision, and this is what keeps it one.

    Fixtures create and drop their own disposable databases, so they legitimately
    open engines on a URL this rule cannot trace to `Settings`. If the tests tree
    ever stopped containing such a caller, the exclusion would be dead weight and
    somebody should delete it — so its absence fails here rather than quietly
    widening what the guard is understood to cover.
    """
    rejected = [
        path
        for path in sorted((ROOT / "tests").rglob("*.py"))
        if "__pycache__" not in path.parts
        and unvalidated_connections(path.read_text(encoding="utf-8"), str(path))
    ]
    assert rejected, (
        "no test opens an engine on a disposable URL; the exclusion of tests/ from "
        "PRODUCTION_ROOTS no longer buys anything and should be removed"
    )
    assert not any(path.is_relative_to(ROOT / "tests") for path in CONNECTION_OPENERS)
