"""A command may not read a caller-supplied field before checking its type.

The ninth independent review measured what the absence of this rule is worth.
`SearchEntities.__post_init__` called `self.query.strip()` with no preceding
`isinstance` check, so `POST /v1/entities.search` with `{"query": 123}` raised
`AttributeError` — which is not a `TypeError`, so `normalization._command` did
not convert it, and not an `ApplicationError`, so the HTTP transport did not
render it. It escaped to Starlette as a bare `500 Internal Server Error`: no
envelope, no typed code, no correlation identifier. It fired *before* the
relationship-intelligence off-switch, so a build with the plane disabled — the
shipped default — answered it too.

The rule already existed. `SearchTasks`, `SearchKnowledge` and `SearchCaptures`
each open `__post_init__` with `if not isinstance(self.query, str)`. Three
commands followed it and two did not, and nothing could tell them apart, which
is this campaign's recurring shape: a rule applied where a reviewer pointed
rather than to the population it names. `tasks.create` carried the same defect
at the merge base and was found only by the same sweep.

**What it detects.** The population is derived, not listed. Every command in
`my_pa.application.commands` is read — a command being any module-level class
carrying a `capability` `ClassVar` — and every one of its fields annotated
exactly `str` is examined. If `__post_init__` dereferences that field
(`self.<field>.strip()`, `self.<field>.lower()`, any attribute access at all),
then an `isinstance(self.<field>, str)` check must appear *earlier in the
statement order* of the same `__post_init__`. Presence is not enough: a check
written below the dereference cannot prevent it.

Fields annotated `str | None`, `int`, a domain enum, or anything else are out of
scope here — they are guarded by `_identifier`, `_positive`, `_moment` and their
siblings, which type-check what they are handed. This module is about the fields
those helpers never see, because the command reads them itself.

**Why the transport's terminal catch is not a substitute.** `adapters/http/app.py`
now carries the `except Exception` the CLI and MCP transports always had, so a
future miss degrades to an `internal_error` envelope rather than a bare `500`.
That is a floor, not a fix: `internal_error` says "this is our fault, retrying
will not help", and a caller who sent a number where a string belongs is owed
`invalid_request` naming the field. The catch bounds the blast radius of a miss;
this test is what makes the miss red.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

import pytest

from my_pa.application import commands as commands_module
from my_pa.application.errors import InvalidRequestError, SafeDetail

_SOURCE = Path(inspect.getfile(commands_module))

#: A value of the wrong type, used both to measure the helpers and to state the
#: rule. An `int` rather than `None`, because `None` is a legitimate value for
#: every optional field and would measure a different rule.
_NOT_A_STRING = 123


def _guarding_helpers() -> frozenset[str]:
    """The helpers that refuse a non-string, measured rather than listed.

    `_text` and `_identifier` both type-check what they are handed — the latter
    by delegating to `validate_identifier`, which fails closed on a non-string
    for the reason its own comment gives. A command that routes a field through
    either has checked the type, and reporting it as unguarded would be a false
    positive that trains a reader to ignore this module.

    The alternative — naming the safe helpers in a literal here — is the
    hardcoded-population shape this campaign has been caught by before: the
    list is right when written and silently wrong the first time a helper stops
    checking. So each is *called* with a non-string and classified by what it
    raises. A helper that answers `InvalidRequestError` guards; one that raises
    `AttributeError` or `TypeError` does not, and its callers stay in the
    population below.
    """
    guarding: set[str] = set()
    for name, helper in vars(commands_module).items():
        if not name.startswith("_") or not callable(helper):
            continue
        try:
            parameters = list(inspect.signature(helper).parameters.values())
        except (TypeError, ValueError):
            continue
        if not parameters:
            continue
        arguments: list[Any] = [_NOT_A_STRING]
        for parameter in parameters[1:]:
            if parameter.default is not inspect.Parameter.empty:
                continue
            annotation = str(parameter.annotation)
            if "SafeDetail" in annotation:
                arguments.append(SafeDetail.QUERY)
            elif "IdKind" in annotation:
                arguments.append(None)
            else:
                arguments = []
                break
        if not arguments:
            continue
        try:
            helper(*arguments)
        except InvalidRequestError:
            # The refusal a caller is owed: this helper checks the type.
            guarding.add(name)
        except Exception:  # noqa: S112 - the raise *is* the classification
            # `AttributeError`, `TypeError`, or anything else: not a guard, so
            # its callers stay in the population. Nothing is logged because the
            # exception is the measurement rather than an incident.
            continue
    return frozenset(guarding)


_GUARDING = _guarding_helpers()


def _module() -> ast.Module:
    return ast.parse(_SOURCE.read_text(encoding="utf-8"))


def _is_command(node: ast.ClassDef) -> bool:
    """A command declares the capability it is the request type for."""
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign) or statement.annotation is None:
            continue
        target = statement.target
        if not isinstance(target, ast.Name) or target.id != "capability":
            continue
        return "ClassVar" in ast.unparse(statement.annotation)
    return False


def _plain_string_fields(node: ast.ClassDef) -> tuple[str, ...]:
    """Fields annotated exactly `str` — not `str | None`, not a `NewType`."""
    fields: list[str] = []
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign) or statement.annotation is None:
            continue
        target = statement.target
        if not isinstance(target, ast.Name):
            continue
        if ast.unparse(statement.annotation).strip() != "str":
            continue
        fields.append(target.id)
    return tuple(fields)


def _post_init(node: ast.ClassDef) -> ast.FunctionDef | None:
    for statement in node.body:
        if isinstance(statement, ast.FunctionDef) and statement.name == "__post_init__":
            return statement
    return None


def _self_attribute(node: ast.AST, field: str) -> bool:
    """`self.<field>` appears somewhere under `node`."""
    return any(
        isinstance(inner, ast.Attribute)
        and inner.attr == field
        and isinstance(inner.value, ast.Name)
        and inner.value.id == "self"
        for inner in ast.walk(node)
    )


def _dereferences(node: ast.AST, field: str) -> bool:
    """`self.<field>.<anything>` — the access that raises on a non-string."""
    return any(
        isinstance(inner, ast.Attribute)
        and isinstance(inner.value, ast.Attribute)
        and inner.value.attr == field
        and isinstance(inner.value.value, ast.Name)
        and inner.value.value.id == "self"
        for inner in ast.walk(node)
    )


def _names_the_field(node: ast.expr, field: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == field
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def _type_checks(node: ast.AST, field: str) -> bool:
    """The type is established, either inline or by a helper measured to check it."""
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call):
            continue
        if not isinstance(inner.func, ast.Name):
            continue
        if inner.func.id == "isinstance":
            if len(inner.args) != 2:
                continue
            subject, kind = inner.args
            if _names_the_field(subject, field) and "str" in ast.unparse(kind):
                return True
            continue
        if inner.func.id in _GUARDING and inner.args and _names_the_field(inner.args[0], field):
            return True
    return False


def _commands() -> tuple[ast.ClassDef, ...]:
    return tuple(
        node for node in _module().body if isinstance(node, ast.ClassDef) and _is_command(node)
    )


def _unguarded() -> tuple[tuple[str, str], ...]:
    """Every (command, field) that is read before its type is known."""
    offences: list[tuple[str, str]] = []
    for node in _commands():
        body = _post_init(node)
        if body is None:
            continue
        for field in _plain_string_fields(node):
            first_check: int | None = None
            first_read: int | None = None
            for index, statement in enumerate(body.body):
                if not _self_attribute(statement, field):
                    continue
                if first_check is None and _type_checks(statement, field):
                    first_check = index
                if first_read is None and _dereferences(statement, field):
                    first_read = index
            if first_read is None:
                continue
            if first_check is None or first_check > first_read:
                offences.append((node.name, field))
    return tuple(offences)


def test_the_population_this_module_reads_is_not_empty() -> None:
    """An anti-vacuity floor: a parse that finds nothing must not read as clean.

    The rule below is a statement about a set. If `_commands` or
    `_plain_string_fields` stopped matching — a decorator change, a move to
    `Annotated[str, ...]`, a rename of `capability` — every assertion in this
    module would pass over an empty set and report the codebase compliant. The
    floors are deliberately far below the current figures so ordinary additions
    do not touch them, and far above zero so a broken reader does.
    """
    found = _commands()
    assert len(found) >= 40, f"only {len(found)} commands parsed from {_SOURCE}"
    read = [
        (node.name, field)
        for node in found
        if _post_init(node) is not None
        for field in _plain_string_fields(node)
        if _dereferences(_post_init(node), field)  # type: ignore[arg-type]
    ]
    assert len(read) >= 8, f"only {len(read)} dereferenced string fields parsed"


@pytest.mark.parametrize(
    "command",
    [node.name for node in _commands()],
)
def test_every_command_checks_a_string_field_before_reading_it(command: str) -> None:
    """Per command, so a failure names the one that regressed."""
    offending = [field for name, field in _unguarded() if name == command]
    assert not offending, (
        f"{command}.__post_init__ reads {', '.join(offending)} before checking "
        f"it is a string. A caller sending a non-string reaches an "
        f"AttributeError instead of an InvalidRequestError naming the field. "
        f"See SearchTasks in {_SOURCE.name} for the shape."
    )


def test_no_command_anywhere_reads_a_string_field_before_checking_it() -> None:
    """The same rule stated over the whole set, so a *new* command is covered.

    The parametrized test above is built from the commands present when the
    module is imported, which is every command — but a reader of the failure
    output benefits from seeing the whole offending set at once rather than one
    parametrization at a time.
    """
    assert _unguarded() == ()
