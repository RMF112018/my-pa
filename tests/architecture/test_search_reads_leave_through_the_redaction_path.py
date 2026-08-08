"""Every database read a search module performs leaves through its redaction path.

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

So this is the control the prose was not. The rules are stated once, here, and
derived from each module's own syntax tree rather than from a list of call sites
a reviewer would have to keep current:

    1. a call that touches the connection is either wrapped in the redaction
       handler where it is written, or it is a call to a function of this module
       that is itself wrapped that way;
    2. the value such a function returns is not unpacked by a further call,
       because by then the handler has been left.

"Touches the connection" is decided from the annotations: a parameter annotated
`Connection`, used as the receiver of a call or passed as an argument to one.
That is what makes a delegated read — `coverage_for(connection, ...)` — count
exactly as much as `connection.execute(...)` does, which is the distinction the
hole lived in. The wrapping is checked by shape and not by name: the call sits
in the body of a `try` whose two handlers are exactly `RETRYABLE` then
`{CATCH_ALL}`, no handler body raises, and the enclosing function raises both of
the module's redacted errors outside every handler. That last clause is the
property the module's own docstring argues for and could not enforce: the
`raise` placed outside the `except` block so the original is not left on
`__context__` for a rendered traceback to print.

**Rule 2 is the structural half, and it is worth being exact about what it is
and is not.** `_execute` used to return the `CursorResult`, so every caller wrote
`_execute(...).one_or_none()` or `_execute(...).all()` — and the `try` inside
`_execute` had been left before the dot ran. A `MultipleResultsFound` would have
propagated raw, outside section 10's taxonomy and outside the envelope. **Nothing
reached that**: the only `one_or_none` read filters on a primary key, and psycopg
buffers a result set so `.all()` performs no I/O. It is a false *guarantee*
rather than an exploitable path, and the fix is to pass the row shape into the
handler rather than apply it afterwards. Rule 2 is what keeps it fixed.

**What the handler clause does and does not enforce, stated exactly, because two
earlier versions of this docstring overstated it.** Requiring both error names
outside every handler catches a collapse by *deletion* — dropping the
`SearchUnavailableError` raise makes this test fail. Requiring the two handler
sets *exactly*, and in order, now also catches two things the superset check it
replaced could not:

- **a collapse by merge.** Folding the handlers into one
  `except (OperationalError, InterfaceError, SQLAlchemyError, ValueError)` while
  keeping both `raise` statements reports every database failure as internal.
  The old check asked only that the caught set be a *superset* of three names,
  so it passed. It is now a mismatch on both handlers.
- **an omitted name.** A superset check can never fail for a name that is
  missing from the required set, which is exactly why the guard could not see
  that `DisconnectionError`, SQLAlchemy's `TimeoutError` and the builtin
  `TimeoutError` were all classified as this system's fault — the last of them
  not classified at all, since it is an `OSError` and not a `SQLAlchemyError`.
  `RETRYABLE` below is now the declaration of that set and a handler that drops
  one of its names reddens.

What is still not proved here is behavioural: that the wrapped call really
produces a bare error against a live server, and that the *split* between the two
handlers means what it says. `tests/security/test_query_is_data_not_sql.py`
proves both — the first by breaking a schema under a real search, the second by
substituting each failure in turn and asserting the classification. A syntactic
guard that claimed the semantic property would be this campaign's own failure
mode written into the gate.

**Two modules, not one, and the boundary is a contract rather than a directory.**
`MODULES` below carries `persistence.search` and `persistence.capture_search`,
which are the two modules that publish a redaction contract, each with its own
pair of redacted error names. The rule was previously not merely un-run on the
sibling — it was *not expressible* for it, because the module path and the error
names were module-level constants consumed by one assertion. The other eleven
`persistence` modules are deliberately **out**: they publish no redaction
contract, their nonzero counts are not defects, and extending this scan to them
would turn a guard into a source of exceptions.

Two syntactic limits, named rather than left to be found. `_connection_parameters`
collects only *parameters* annotated `Connection`, so a read reached through a
local alias — `reader = connection; coverage_for(reader, ...)` — is invisible to
this scan, and the function reports zero reads rather than an unwrapped one.
And `_is_wrapped` tests *lexical* containment, so a call bound inside a `try`
and invoked after it, through `partial` or a nested `def`, counts as wrapped.
Neither is backstopped by the behavioural tests, which cover today's reads
rather than tomorrow's. Making the scan alias-aware is a real dataflow problem
and is not attempted here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

PERSISTENCE = ROOT / "src" / "my_pa" / "infrastructure" / "persistence"

#: The exception classes a redaction handler must separate, and the whole of the
#: retryable side. Derived from the hierarchy rather than from the two names a
#: driver raises most: `DisconnectionError` and SQLAlchemy's `TimeoutError` — a
#: pool checkout that waited out `pool_timeout`, reachable by construction
#: because the engine disables overflow — are `SQLAlchemyError` subclasses that
#: are neither `OperationalError` nor `InterfaceError`, and the builtin
#: `TimeoutError` is an `OSError`, so it and the socket failures beside it are
#: not `SQLAlchemyError` at all. `PoolTimeoutError` is the alias the modules
#: import SQLAlchemy's under, so that the builtin keeps its own name.
RETRYABLE: frozenset[str] = frozenset(
    {
        "OperationalError",
        "InterfaceError",
        "DisconnectionError",
        "PoolTimeoutError",
        "OSError",
    }
)

#: The second handler, and it is `Exception` rather than `SQLAlchemyError` on
#: purpose. A promise about *any* failure of a read cannot be carried by a
#: handler naming one library's base class; that is how the builtin
#: `TimeoutError` got out.
CATCH_ALL = "Exception"

#: The two modules that publish a redaction contract, each with the pair of
#: errors it redacts into. Requiring both names catches a collapse by deletion —
#: dropping either raise fails this test.
#: `(unavailable, internal)` — ordered, not a set, and the order is load-bearing.
#: `_answers_with` has to know *which* of the two means "retryable" in order to
#: check that the retryable handler is what selects it. A set cannot say.
MODULES: dict[str, tuple[str, str]] = {
    "search.py": ("SearchUnavailableError", "SearchInternalError"),
    "capture_search.py": ("CaptureSearchUnavailableError", "CaptureSearchInternalError"),
}


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


def _raises_outside_handlers(function: ast.FunctionDef, redacted: tuple[str, str]) -> set[str]:
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
        and raised.exc.func.id in redacted
    }


def _flag_assignment(handler: ast.ExceptHandler) -> tuple[str, bool] | None:
    """The `<name> = <True|False>` a handler body consists of, or `None`."""
    if len(handler.body) != 1:
        return None
    statement = handler.body[0]
    if (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, bool)
    ):
        return statement.targets[0].id, statement.value.value
    return None


def _truth(test: ast.expr, flag: str) -> bool | None:
    """`True` if `test` means `flag`, `False` if it means `not flag`, else `None`."""
    if isinstance(test, ast.Name) and test.id == flag:
        return True
    if (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Name)
        and test.operand.id == flag
    ):
        return False
    return None


def _raised_when(body: list[ast.stmt], flag: str, value: bool) -> str | None:
    """Which redacted error this body raises when `flag` holds `value`.

    A three-statement interpreter — `raise`, `if`, and fall through — which is the
    whole of the shape both modules use. Anything it cannot evaluate answers
    `None` and fails the check, which is the fail-closed direction.
    """
    for statement in body:
        if isinstance(statement, ast.Raise):
            return _raised_name(statement)
        if isinstance(statement, ast.If):
            truth = _truth(statement.test, flag)
            if truth is None:
                return None
            taken = _raised_when(
                statement.body if truth is value else statement.orelse, flag, value
            )
            if taken is not None:
                return taken
    return None


def _answers_with(function: ast.FunctionDef, flag: str, redacted: tuple[str, str]) -> bool:
    """Whether `flag` being true is what selects the *unavailable* error.

    The last link, and it was missing. `_classifies` checked the handlers' names
    and their order and never their bodies, so swapping the two assignments —
    retryable sets `False`, everything else sets `True` — passed this guard with
    every name present and every raise outside, while reporting a dropped
    connection as this system's fault and a missing column as retryable.

    **Checked by meaning and not by spelling, and the first version of this
    function got that wrong.** It required the literal shape `if <flag>: raise
    <unavailable>` with the other raise below, which made
    `if not unavailable: raise <internal>` / `raise <unavailable>` — an exact
    behavioural equivalent — fail. Measured: that rewrite reddened this guard and
    passed all eighteen behavioural classification cases, which is the definition
    of a false positive. A guard that rejects a correct rewrite trains a reader to
    edit the guard, and the next edit is the one that matters. So both branches
    are evaluated instead, and only the answer is asserted.
    """
    unavailable, internal = redacted
    return (
        _raised_when(function.body, flag, True) == unavailable
        and _raised_when(function.body, flag, False) == internal
    )


def _raised_name(statement: ast.stmt) -> str | None:
    """The class name a `raise Name(...)` names."""
    if (
        isinstance(statement, ast.Raise)
        and isinstance(statement.exc, ast.Call)
        and isinstance(statement.exc.func, ast.Name)
    ):
        return statement.exc.func.id
    return None


def _classifies(node: ast.Try, function: ast.FunctionDef, redacted: tuple[str, str]) -> bool:
    """Whether this `try` separates the retryable set from everything else.

    Exactly two handlers, in order, catching exactly `RETRYABLE` and exactly
    `{CATCH_ALL}`, neither raising, **and each assigning the flag that the raises
    below are selected by**. Exact rather than superset: a superset passes for
    every name it does not require, which is why the check this replaced could
    not see a retryable class classified as internal. Ordered, because a
    `CATCH_ALL` written first makes the retryable handler unreachable and Python
    will not say so. Bodies, because names and order alone describe the shape of
    an answer without constraining the answer — see `_answers_with`.

    The behavioural holder of this property is
    `tests/security/test_query_is_data_not_sql.py`, which substitutes nine
    failures into both modules and asserts the classification each gets. This is
    the structural half: it fails on a rearrangement that inverts the meaning
    even where no test happens to cover the class that moved.
    """
    if len(node.handlers) != 2:
        return False
    retryable, catch_all = node.handlers
    if any(
        isinstance(inner, ast.Raise) for handler in node.handlers for inner in ast.walk(handler)
    ):
        return False
    if _named_types(retryable.type) != RETRYABLE or _named_types(catch_all.type) != {CATCH_ALL}:
        return False
    set_on_retryable = _flag_assignment(retryable)
    set_on_everything_else = _flag_assignment(catch_all)
    if set_on_retryable is None or set_on_everything_else is None:
        return False
    flag, retryable_value = set_on_retryable
    if (flag, retryable_value) != (set_on_everything_else[0], True):
        return False
    if set_on_everything_else[1] is not False:
        return False
    return _answers_with(function, flag, redacted)


def _redaction_bodies(function: ast.FunctionDef, redacted: tuple[str, str]) -> list[list[ast.stmt]]:
    """The `try` bodies in `function` that are a complete redaction handler."""
    if _raises_outside_handlers(function, redacted) != set(redacted):
        return []
    return [
        node.body
        for node in ast.walk(function)
        if isinstance(node, ast.Try) and _classifies(node, function, redacted)
    ]


def _is_wrapped(call: ast.Call, bodies: list[list[ast.stmt]]) -> bool:
    return any(
        any(call is node for statement in body for node in ast.walk(statement)) for body in bodies
    )


def _safe_functions(
    functions: list[ast.FunctionDef],
    reads: dict[str, list[ast.Call]],
    wrapped: dict[str, list[ast.Call]],
) -> set[str]:
    """The functions whose every read leaves through the redaction path.

    A fixed point rather than a single pass, because the module's reads are two
    deep: `_context` is safe because it calls `_execute`, and `_execute` is safe
    because its own read sits in a redaction handler. Growing the safe set until
    it stops growing is what lets the rule be stated about calls rather than
    about a hierarchy somebody has to maintain.
    """
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
    return safe


def _row_shapes(functions: list[ast.FunctionDef]) -> set[str]:
    """The module's declared row shapes, derived rather than listed.

    A row shape is a function of this module whose one parameter is annotated
    `CursorResult` — `_one_or_none`, `_every_row`, `_exactly_one`. Derived from
    the annotation so that adding a fourth needs no edit here, and so that this
    guard cannot drift from the module the way a maintained list would.
    """
    shapes: set[str] = set()
    for function in functions:
        arguments = (*function.args.posonlyargs, *function.args.args)
        if len(arguments) != 1:
            continue
        annotation = arguments[0].annotation
        if isinstance(annotation, ast.Subscript):
            annotation = annotation.value
        if isinstance(annotation, ast.Name) and annotation.id == "CursorResult":
            shapes.add(function.name)
    return shapes


def _materializing_functions(functions: list[ast.FunctionDef], shapes: set[str]) -> set[str]:
    """The functions that take a row shape as an argument.

    Derived, not named: a function with more than one parameter, one of whose
    annotations mentions `CursorResult` — which is `_execute` and, if a second
    one is ever written, that one too. The distinction from `_row_shapes` is the
    parameter count: a shape *is* the callable, a materializing function
    *receives* one.

    Rule 3 is scoped to calls to these. The first version scoped it to every
    reading function and reported `search_extractions` calling `_context`,
    `_matches` and `_coverage` — none of which takes a materializer, because
    each already passes its own. Measured, not reasoned: that is what the first
    run reported.
    """
    materializing: set[str] = set()
    for function in functions:
        if function.name in shapes:
            continue
        arguments = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        if len(arguments) < 2:
            continue
        if any(
            isinstance(node, ast.Name) and node.id == "CursorResult"
            for argument in arguments
            if argument.annotation is not None
            for node in ast.walk(argument.annotation)
        ):
            materializing.add(function.name)
    return materializing


def _escaping_cursors(
    functions: list[ast.FunctionDef],
    reads: dict[str, list[ast.Call]],
    reading: set[str],
    shapes: set[str],
) -> list[str]:
    """Every read whose row shape is not one the module declares.

    **This is the rule that makes rule 2's narrowness safe, and it exists because
    rule 2's narrowness was not.** Rule 2 matches `safe_read(...).attr()` and
    nothing else, so three shapes reinstated the defect it was written for while
    both it and rule 1 reported clean: assigning the result and unpacking it on
    the next line, subscripting it, and — the one that actually matters —
    `_execute(connection, statement, lambda result: result)`, an identity
    materializer that hands the caller the live `CursorResult` again. mypy cannot
    object: `lambda result: result` satisfies `Callable[[CursorResult], Rows]`
    perfectly.

    Constraining the *materializer* instead of the use of the result is the
    assumption-level fix. When every read materializes through one of the
    module's declared shapes, what comes back is a `Row`, a `Row | None` or a
    `Sequence[Row]` — never a cursor — so unpacking it afterwards, however it is
    spelled, cannot perform I/O and cannot raise a database error outside the
    handler. Rule 2 then stops being the guarantee and becomes a second, cheaper
    net for the one spelling it does catch.
    """
    materializing = _materializing_functions(functions, shapes) & reading
    return sorted(
        f"{function.name}:{call.lineno}"
        for function in functions
        for call in reads[function.name]
        if isinstance(call.func, ast.Name)
        and call.func.id in materializing
        and not any(
            isinstance(argument, ast.Name) and argument.id in shapes
            for argument in (*call.args, *(keyword.value for keyword in call.keywords))
        )
    )


def _scan(
    source: str, filename: str, redacted: tuple[str, str]
) -> tuple[list[str], list[str], list[str]]:
    """`(reads outside the path, results unpacked after it, cursors that escape)`."""
    tree = ast.parse(source, filename=filename)
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    reads = {
        function.name: _reads(function, _connection_parameters(function)) for function in functions
    }
    wrapped = {
        function.name: [
            call
            for call in reads[function.name]
            if _is_wrapped(call, _redaction_bodies(function, redacted))
        ]
        for function in functions
    }
    safe = _safe_functions(functions, reads, wrapped)

    escaping = sorted(
        f"{function.name}:{call.lineno}"
        for function in functions
        for call in reads[function.name]
        if call not in wrapped[function.name]
        and not (isinstance(call.func, ast.Name) and call.func.id in safe)
    )
    # Only the safe functions that *read*. `_safe_functions` is a fixed point
    # over "every read is wrapped", which a function with no reads at all
    # satisfies vacuously — so `safe` contains every statement builder in the
    # module, and rule 2 applied to it would report `_tsquery(request).bool_op(…)`
    # as a read unpacked after its handler. There is no handler; there is no
    # read. Measured rather than reasoned: that is what the first run of this
    # scan reported, in `match_statement` in both modules.
    reading = {name for name in safe if reads[name]}
    unpacked = sorted(
        f"{function.name}:{node.lineno}"
        for function in functions
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Call)
        and isinstance(node.func.value.func, ast.Name)
        and node.func.value.func.id in reading
    )
    return escaping, unpacked, _escaping_cursors(functions, reads, reading, _row_shapes(functions))


def unredacted_reads(source: str, filename: str, redacted: tuple[str, str]) -> list[str]:
    """Every connection-touching call in `source` that escapes the redaction path."""
    return _scan(source, filename, redacted)[0]


def reads_unpacked_after_the_handler(
    source: str, filename: str, redacted: tuple[str, str]
) -> list[str]:
    """Every `safe_read(...).something()` — the dot runs after the `try` is left."""
    return _scan(source, filename, redacted)[1]


def reads_without_a_declared_row_shape(
    source: str, filename: str, redacted: tuple[str, str]
) -> list[str]:
    """Every read that materializes through something the module does not declare."""
    return _scan(source, filename, redacted)[2]


@pytest.mark.parametrize("module", sorted(MODULES))
def test_every_read_a_search_performs_leaves_through_the_redaction_path(module: str) -> None:
    """Rule 1, applied to both modules that state it.

    This failed at `634890e` with `_coverage:<line>` — `coverage_for` on the
    connection, in a `try` that caught `ValueError` alone.
    """
    path = PERSISTENCE / module
    escaping = unredacted_reads(path.read_text(encoding="utf-8"), str(path), MODULES[module])
    assert escaping == [], f"reads outside the redaction path in {module}: {escaping}"


@pytest.mark.parametrize("module", sorted(MODULES))
def test_no_read_is_unpacked_after_its_handler_has_been_left(module: str) -> None:
    """Rule 2, applied to both modules that state it.

    This failed before the row shape became an argument, with `_context:<line>`,
    `_limitation_tokens:<line>`, `_matches:<line>` and — in the sibling —
    `search_captures:<line>` twice.
    """
    path = PERSISTENCE / module
    unpacked = reads_unpacked_after_the_handler(
        path.read_text(encoding="utf-8"), str(path), MODULES[module]
    )
    assert unpacked == [], f"results unpacked outside the handler in {module}: {unpacked}"


@pytest.mark.parametrize("module", sorted(MODULES))
def test_every_read_materializes_through_a_declared_row_shape(module: str) -> None:
    """Rule 3, applied to both modules that state it.

    The rule that makes "the cursor never leaves the handler" true rather than
    merely usually true. See `_escaping_cursors` for the three shapes that
    defeated rule 2 alone.
    """
    path = PERSISTENCE / module
    escaping = reads_without_a_declared_row_shape(
        path.read_text(encoding="utf-8"), str(path), MODULES[module]
    )
    assert escaping == [], f"reads with an undeclared row shape in {module}: {escaping}"


#: The three shapes that reinstate item 3's defect while rules 1 and 2 report
#: clean. The first two are ordinary idioms in this repository; the third is the
#: one that matters, because it hands the caller the live cursor back and
#: typechecks perfectly.
BYPASSES = {
    "assign, then unpack on the next line": (
        "    r = _execute(connection, statement, _one_or_none)\n    return r.one_or_none()",
        [],
    ),
    "subscript the result": ("    return _execute(connection, statement, _every_row)[0]", []),
    "an identity materializer": (
        "    cursor = _execute(connection, statement, lambda result: result)\n"
        "    return cursor.all()",
        ["_context"],
    ),
    "a declared row shape": ("    return _execute(connection, statement, _one_or_none)", []),
}

UNSHAPED = """\
from sqlalchemy import Connection, CursorResult
from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError


def _one_or_none(result: CursorResult[Any]) -> object:
    return result.one_or_none()


def _every_row(result: CursorResult[Any]) -> object:
    return result.all()


def _execute[Rows](
    connection: Connection,
    statement: object,
    materialize: Callable[[CursorResult[Any]], Rows],
) -> Rows:
    unavailable = False
    try:
        return materialize(connection.execute(statement))
    except (OperationalError, InterfaceError, DisconnectionError, PoolTimeoutError, OSError):
        unavailable = True
    except Exception:
        unavailable = False
    if unavailable:
        raise SearchUnavailableError("unavailable")
    raise SearchInternalError("internal")


def _context(connection: Connection, statement: object) -> object:
{read}
"""


@pytest.mark.parametrize("name", sorted(BYPASSES))
def test_the_row_shape_scan_catches_what_the_unpacking_scan_cannot(name: str) -> None:
    """Non-vacuity for rule 3, and the demonstration that rule 2 needed it.

    Every case asserts **both** scans, so the record shows what each one sees.
    Rule 2 reports nothing for any of the four — including the identity
    materializer, whose cursor is stored before it is unpacked — and rule 3
    reports exactly the one that lets a cursor out. The fourth case is the
    control: the correct form, clean under both.
    """
    read, expected = BYPASSES[name]
    source = UNSHAPED.format(read=read)
    redacted = MODULES["search.py"]
    by_shape = reads_without_a_declared_row_shape(source, f"<planted: {name}>", redacted)
    by_unpacking = reads_unpacked_after_the_handler(source, f"<planted: {name}>", redacted)
    assert sorted({entry.split(":")[0] for entry in by_shape}) == expected
    assert by_unpacking == [], (
        "rule 2 is expected to see none of these; rule 3 is what makes that safe"
    )


#: A module shaped like `persistence.search` and nothing more: one wrapped read
#: of its own, and one delegated read whose handler is the variable under test.
#: Written out rather than cut from the real file, so that the control is a
#: statement of the rule instead of a copy of today's implementation.
PLANTED = """\
from sqlalchemy import Connection
from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from elsewhere import coverage_for


def _execute(connection: Connection, statement: object, materialize: object) -> object:
    unavailable = False
    try:
        return materialize(connection.execute(statement))
    except (OperationalError, InterfaceError, DisconnectionError, PoolTimeoutError, OSError):
        unavailable = True
    except Exception:
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
    _execute(connection, "select 1", _every_row)
    return _coverage(connection, enrollment_id)
"""

#: The hole, as it stood: the delegated read is inside a `try`, which is what
#: made it look handled, and the handler classifies nothing a database raises.
HOLE = """\
    except ValueError:
        pass"""

#: The same read, redacted.
CLOSED = """\
    except (OperationalError, InterfaceError, DisconnectionError, PoolTimeoutError, OSError):
        unavailable = True
    except Exception:
        unavailable = False"""

#: The discrimination that would pass this test while destroying the answer:
#: the classes are all named, but the raise is inside the handler, where
#: `__context__` keeps the original for a traceback to render.
RAISE_INSIDE = """\
    except (OperationalError, InterfaceError, DisconnectionError, PoolTimeoutError, OSError):
        raise SearchUnavailableError("unavailable") from None
    except Exception:
        raise SearchInternalError("internal") from None"""

#: One name dropped from the retryable set, which is the whole reason the
#: superset check was replaced. `OSError` is the one that matters most — it is
#: the only member that is not a `SQLAlchemyError`, so dropping it does not
#: merely misclassify a failure, it lets one out of the module entirely.
DROPPED_NAME = """\
    except (OperationalError, InterfaceError, DisconnectionError, PoolTimeoutError):
        unavailable = True
    except Exception:
        unavailable = False"""

#: The collapse by merge the previous version of this guard could not see: every
#: name is present, both raises are outside, and every database failure is
#: reported as this system's fault.
MERGED = """\
    except (OperationalError, InterfaceError, DisconnectionError, PoolTimeoutError, OSError,
            Exception):
        unavailable = False"""

#: The catch-all first, which makes the retryable handler unreachable. Python
#: accepts it silently and every failure becomes internal.
CATCH_ALL_FIRST = """\
    except Exception:
        unavailable = False
    except (OperationalError, InterfaceError, DisconnectionError, PoolTimeoutError, OSError):
        unavailable = True"""

PLANTED_REDACTED = ("SearchUnavailableError", "SearchInternalError")


@pytest.mark.parametrize(
    ("name", "handler", "expected"),
    [
        # The delegated read escapes, and so does the caller that hands it the
        # connection: a function is only as redacted as what it delegates to.
        ("the hole this closes", HOLE, ["_coverage", "search"]),
        ("the same read, redacted", CLOSED, []),
        ("a raise left inside the handler", RAISE_INSIDE, ["_coverage", "search"]),
        ("a retryable name dropped", DROPPED_NAME, ["_coverage", "search"]),
        ("the handlers merged into one", MERGED, ["_coverage", "search"]),
        ("the catch-all written first", CATCH_ALL_FIRST, ["_coverage", "search"]),
    ],
)
def test_the_scan_discriminates(name: str, handler: str, expected: list[str]) -> None:
    """Non-vacuity for rule 1, and its paired control.

    A scan that reported everything would pass the test above the day the rule
    was broken, and a scan that reported nothing would pass it for ever. The
    same planted module is run six ways: the delegated read left in the handler
    the hole had, the same read wrapped, the same read wrapped but with the
    `raise` moved inside the `except` block, one retryable name dropped, the two
    handlers merged, and the catch-all written first. Only the second is clean,
    so the scan is answering the question rather than its own name.

    The last three are the ones the superset check this replaced let through:
    each of them passed it, and two of them — the merge and the reordering —
    report every database failure as non-retryable.

    Compared by function and not by line, because a line number would pin the
    layout of the planted source rather than the rule it demonstrates.
    """
    escaping = unredacted_reads(
        PLANTED.format(handler=handler), f"<planted: {name}>", PLANTED_REDACTED
    )
    assert sorted({entry.split(":")[0] for entry in escaping}) == expected


#: The handler bodies swapped: every name present, both raises outside, the order
#: intact, and every answer inverted. This passed the guard before `_classifies`
#: looked at bodies.
BODIES_SWAPPED = """\
    except (OperationalError, InterfaceError, DisconnectionError, PoolTimeoutError, OSError):
        unavailable = False
    except Exception:
        unavailable = True"""

#: The decision as it is written, and three rewrites of it. Two mean the same
#: thing and two invert the answer; no two of them differ in more than the
#: placement of a `not` and two identifiers.
_DECISION = (
    '    if unavailable:\n        raise SearchUnavailableError("unavailable")\n'
    '    raise SearchInternalError("internal")'
)
_INVERTED_TEST = (
    '    if not unavailable:\n        raise SearchInternalError("internal")\n'
    '    raise SearchUnavailableError("unavailable")'
)
_SWAPPED_RAISES = (
    '    if unavailable:\n        raise SearchInternalError("internal")\n'
    '    raise SearchUnavailableError("unavailable")'
)


@pytest.mark.parametrize(
    ("name", "handler", "decision", "expected"),
    [
        ("as written", CLOSED, _DECISION, []),
        # The reviewer's finding: names and order say nothing about the answer.
        ("the handler bodies swapped", BODIES_SWAPPED, _DECISION, ["_coverage", "search"]),
        # The same decision, spelled the other way round. Behaviourally identical,
        # and an earlier version of `_answers_with` rejected it — a guard that
        # rejects a correct rewrite teaches a reader to edit the guard.
        ("the test negated and the raises reordered", CLOSED, _INVERTED_TEST, []),
        # The inversion that is a defect: same shape, opposite answer.
        (
            "the two raises swapped",
            CLOSED,
            _SWAPPED_RAISES,
            ["_coverage", "_execute", "search"],
        ),
    ],
)
def test_the_scan_checks_the_answer_and_not_its_spelling(
    name: str, handler: str, decision: str, expected: list[str]
) -> None:
    """Non-vacuity for the classification check, with both kinds of control.

    Four modules that differ only in how the retryable decision is written. Two
    are correct and must be clean; two invert what a caller is told and must be
    flagged. A guard that pinned the spelling would pass the first and fail the
    third; a guard that checked only names and order — which is what this one did
    — passes the second.
    """
    source = PLANTED.format(handler=handler).replace(_DECISION, decision)
    escaping = unredacted_reads(source, f"<planted: {name}>", PLANTED_REDACTED)
    assert sorted({entry.split(":")[0] for entry in escaping}) == expected


#: The same module, with the row shape applied where the two versions of this
#: module differ: inside the handler as an argument, or outside it as a dot on
#: what `_execute` returned.
UNPACKED = """\
from sqlalchemy import Connection
from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError


def _execute(connection: Connection, statement: object, materialize: object) -> object:
    unavailable = False
    try:
        return materialize(connection.execute(statement))
    except (OperationalError, InterfaceError, DisconnectionError, PoolTimeoutError, OSError):
        unavailable = True
    except Exception:
        unavailable = False
    if unavailable:
        raise SearchUnavailableError("unavailable")
    raise SearchInternalError("internal")


def _context(connection: Connection, statement: object) -> object:
    return {read}
"""


@pytest.mark.parametrize(
    ("name", "read", "expected"),
    [
        (
            "the row shape applied after the handler was left",
            "_execute(connection, statement).one_or_none()",
            ["_context"],
        ),
        (
            "the row shape passed into the handler",
            "_execute(connection, statement, _one_or_none)",
            [],
        ),
    ],
)
def test_the_unpacking_scan_discriminates(name: str, read: str, expected: list[str]) -> None:
    """Non-vacuity for rule 2, and its paired control.

    Both plants call a function the first scan calls safe, so neither is
    reported by rule 1 — which is exactly why rule 2 has to exist separately.
    The difference between them is one dot.
    """
    unpacked = reads_unpacked_after_the_handler(
        UNPACKED.format(read=read), f"<planted: {name}>", PLANTED_REDACTED
    )
    assert sorted({entry.split(":")[0] for entry in unpacked}) == expected
