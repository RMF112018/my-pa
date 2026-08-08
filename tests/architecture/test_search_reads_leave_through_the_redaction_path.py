"""Every database read `persistence.search` performs leaves through its redaction path.

`persistence.search` states a guarantee its callers rely on: a database failure
becomes one of that module's own typed errors, carrying no statement, no bound
parameter, and no original exception on `__cause__` or `__context__`. It held
that for the statements it *builds*, because each one goes through `_execute`.
It did not hold it for the statement it *delegates*: `_coverage` called
`coverage_for`, which runs its own statements on the same connection, inside a
`try` that caught `ValueError` and nothing else, so a `ProgrammingError` from
the coverage read escaped as a `SQLAlchemyError` whose message carried the SQL
and the bound `enrollment_id`. That hole was disclosed in prose in the module
and scheduled in `docs/plans/mcv-completion-plan.md` section 10, and prose is
what let it survive a whole work package.

So this is the control the prose was not. The rule is stated once, here, and
derived from the module's own syntax tree rather than from a list of call sites
a reviewer would have to keep current:

    a call that touches the connection is either wrapped in the redaction
    handler where it is written, or it is a call to a function of this module
    that is itself wrapped that way.

"Touches the connection" is decided from the annotations: a parameter annotated
`Connection`, used as the receiver of a call or passed as an argument to one.
That is what makes a delegated read — `coverage_for(connection, ...)` — count
exactly as much as `connection.execute(...)` does, which is the distinction the
hole lived in. The wrapping is checked by shape and not by name: the call sits
in the body of a `try` whose handlers name `OperationalError`, `InterfaceError`
and `SQLAlchemyError`, no handler body raises, and the enclosing function raises
both `SearchUnavailableError` and `SearchInternalError` outside every handler.
The last two clauses are the properties the module's own docstring argues for
and could not enforce: the `unavailable`/`internal` discrimination, and the
`raise` placed outside the `except` block so the original is not left on
`__context__` for a rendered traceback to print.

What this does not prove is behavioural: that the wrapped call really produces a
bare error against a live server. `tests/security/test_query_is_data_not_sql.py`
proves that, for a delegated read and for one of this module's own, by breaking
the schema under a real search. Nor does it say anything about `coverage_for`
itself, or about any other module: the claim is that *this* module's reads leave
through *this* module's redaction, and it is bounded to that file.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

MODULE = ROOT / "src" / "my_pa" / "infrastructure" / "persistence" / "search.py"

#: The exception classes a redaction handler must separate. `OperationalError`
#: and `InterfaceError` are the retryable pair and `SQLAlchemyError` is
#: everything else; a handler set missing any of the three either misclassifies
#: a failure or lets it through.
CLASSIFIED: frozenset[str] = frozenset({"OperationalError", "InterfaceError", "SQLAlchemyError"})

#: The errors a redacting function raises, both of them. Requiring both is what
#: keeps a "fix" that collapses the discrimination — everything internal, or
#: everything unavailable — from satisfying this test.
REDACTED: frozenset[str] = frozenset({"SearchUnavailableError", "SearchInternalError"})


def _connection_parameters(function: ast.FunctionDef) -> set[str]:
    """The names this function knows to be a live database connection."""
    arguments = function.args
    return {
        argument.arg
        for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
        if isinstance(argument.annotation, ast.Name) and argument.annotation.id == "Connection"
    }


def _reads(function: ast.FunctionDef, connections: set[str]) -> list[ast.Call]:
    """Every call in `function` that hands the connection to something.

    Both forms count and that is the whole point: `connection.execute(...)`,
    where the connection is the receiver, and `coverage_for(connection, ...)`,
    where it is an argument and the statements are somebody else's.
    """
    found: list[ast.Call] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        receiver = node.func
        if (
            isinstance(receiver, ast.Attribute)
            and isinstance(receiver.value, ast.Name)
            and receiver.value.id in connections
        ):
            found.append(node)
            continue
        passed = (*node.args, *(keyword.value for keyword in node.keywords))
        if any(isinstance(value, ast.Name) and value.id in connections for value in passed):
            found.append(node)
    return found


def _named_types(node: ast.expr | None) -> set[str]:
    """The exception names an `except` clause catches, bare or in a tuple."""
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Tuple):
        names: set[str] = set()
        for element in node.elts:
            names |= _named_types(element)
        return names
    return set()


def _raises_outside_handlers(function: ast.FunctionDef) -> set[str]:
    """The typed errors this function raises with no handler on the stack.

    `raise … from None` clears `__cause__` and leaves the original in
    `__context__`; leaving the handler before raising is what empties it. So a
    raise found inside an `except` body does not count here, which is exactly
    the property the module docstring claims and nothing checked.
    """
    handled = {
        id(node)
        for handler in ast.walk(function)
        if isinstance(handler, ast.ExceptHandler)
        for node in ast.walk(handler)
    }
    return {
        raised.exc.func.id
        for raised in ast.walk(function)
        if isinstance(raised, ast.Raise)
        and id(raised) not in handled
        and isinstance(raised.exc, ast.Call)
        and isinstance(raised.exc.func, ast.Name)
        and raised.exc.func.id in REDACTED
    }


def _redaction_bodies(function: ast.FunctionDef) -> list[list[ast.stmt]]:
    """The `try` bodies in `function` that are a complete redaction handler."""
    if _raises_outside_handlers(function) != REDACTED:
        return []
    bodies: list[list[ast.stmt]] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Try):
            continue
        caught: set[str] = set()
        raises_inside = False
        for handler in node.handlers:
            caught |= _named_types(handler.type)
            raises_inside = raises_inside or any(
                isinstance(inner, ast.Raise) for inner in ast.walk(handler)
            )
        if not raises_inside and caught >= CLASSIFIED:
            bodies.append(node.body)
    return bodies


def _is_wrapped(call: ast.Call, bodies: list[list[ast.stmt]]) -> bool:
    return any(
        any(call is node for statement in body for node in ast.walk(statement)) for body in bodies
    )


def unredacted_reads(source: str, filename: str) -> list[str]:
    """Every connection-touching call in `source` that escapes the redaction path.

    A fixed point rather than a single pass, because the module's reads are two
    deep: `_context` is safe because it calls `_execute`, and `_execute` is safe
    because its own read sits in a redaction handler. Growing the safe set until
    it stops growing is what lets the rule be stated about calls rather than
    about a hierarchy somebody has to maintain.
    """
    tree = ast.parse(source, filename=filename)
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    reads = {
        function.name: _reads(function, _connection_parameters(function)) for function in functions
    }
    wrapped = {
        function.name: [
            call for call in reads[function.name] if _is_wrapped(call, _redaction_bodies(function))
        ]
        for function in functions
    }

    safe: set[str] = set()
    while True:
        grown = {
            function.name
            for function in functions
            if function.name not in safe
            and all(
                call in wrapped[function.name]
                or (isinstance(call.func, ast.Name) and call.func.id in safe)
                for call in reads[function.name]
            )
        }
        if not grown:
            break
        safe |= grown

    return sorted(
        f"{function.name}:{call.lineno}"
        for function in functions
        for call in reads[function.name]
        if call not in wrapped[function.name]
        and not (isinstance(call.func, ast.Name) and call.func.id in safe)
    )


def test_every_read_a_search_performs_leaves_through_the_redaction_path() -> None:
    """The rule, applied to the module that states it.

    This failed at `634890e` with `_coverage:<line>` — `coverage_for` on the
    connection, in a `try` that caught `ValueError` alone.
    """
    escaping = unredacted_reads(MODULE.read_text(encoding="utf-8"), str(MODULE))
    assert escaping == [], f"reads outside the redaction path: {escaping}"


#: A module shaped like `persistence.search` and nothing more: one wrapped read
#: of its own, and one delegated read whose handler is the variable under test.
#: Written out rather than cut from the real file, so that the control is a
#: statement of the rule instead of a copy of today's implementation.
PLANTED = """\
from sqlalchemy import Connection
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError

from elsewhere import coverage_for


def _execute(connection: Connection, statement: object) -> object:
    unavailable = False
    try:
        return connection.execute(statement)
    except (OperationalError, InterfaceError):
        unavailable = True
    except SQLAlchemyError:
        unavailable = False
    if unavailable:
        raise SearchUnavailableError("unavailable")
    raise SearchInternalError("internal")


def _coverage(connection: Connection, enrollment_id: str) -> object:
    unavailable = False
    try:
        return coverage_for(connection, enrollment_id)
{handler}
    if unavailable:
        raise SearchUnavailableError("unavailable")
    raise SearchInternalError("internal")


def search(connection: Connection, enrollment_id: str) -> object:
    _execute(connection, "select 1")
    return _coverage(connection, enrollment_id)
"""

#: The hole, as it stood: the delegated read is inside a `try`, which is what
#: made it look handled, and the handler classifies nothing a database raises.
HOLE = """\
    except ValueError:
        pass"""

#: The same read, redacted.
CLOSED = """\
    except (OperationalError, InterfaceError):
        unavailable = True
    except (SQLAlchemyError, ValueError):
        unavailable = False"""

#: The discrimination that would pass this test while destroying the answer:
#: the classes are all named, but the raise is inside the handler, where
#: `__context__` keeps the original for a traceback to render.
RAISE_INSIDE = """\
    except (OperationalError, InterfaceError):
        raise SearchUnavailableError("unavailable") from None
    except (SQLAlchemyError, ValueError):
        raise SearchInternalError("internal") from None"""


@pytest.mark.parametrize(
    ("name", "handler", "expected"),
    [
        # The delegated read escapes, and so does the caller that hands it the
        # connection: a function is only as redacted as what it delegates to.
        ("the hole this closes", HOLE, ["_coverage", "search"]),
        ("the same read, redacted", CLOSED, []),
        ("a raise left inside the handler", RAISE_INSIDE, ["_coverage", "search"]),
    ],
)
def test_the_scan_discriminates(name: str, handler: str, expected: list[str]) -> None:
    """Non-vacuity, and its paired control.

    A scan that reported everything would pass the test above the day the rule
    was broken, and a scan that reported nothing would pass it for ever. The
    same planted module is run three ways: the delegated read left in the
    handler the hole had, the same read wrapped, and the same read wrapped but
    with the `raise` moved inside the `except` block. Only the middle one is
    clean, so the scan is answering the question rather than its own name.

    Compared by function and not by line, because a line number would pin the
    layout of the planted source rather than the rule it demonstrates.
    """
    escaping = unredacted_reads(PLANTED.format(handler=handler), f"<planted: {name}>")
    assert sorted({entry.split(":")[0] for entry in escaping}) == expected
