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
carrying a `capability` `ClassVar` — and every field whose value, when present,
must be a `str` is examined: `str` and `str | None` alike. If `__post_init__`
uses that field as a string, the field's type must be established *first*, by
source position rather than by statement, so a check written to the right of the
read in one expression does not count.

"Uses it as a string" is two shapes. The obvious one is `self.<field>.strip()`.
The other is `helper(self.<field>, …)` where the helper is not one measured to
type-check — because extracting the read into a helper is how this module was
first made to overlook a live defect, and `commands.py` already does exactly
that five times over.

**The exclusions this module used to carry were wrong, and it took a tenth
review to measure it.** `str | None` was out of scope, justified by the claim
that such fields "are guarded by `_identifier`, `_positive`, `_moment` and their
siblings". `UpdateTask.title`, `TransitionTask.closure_evidence_ref` and
`DecideReviewCase.corrected_value` are handed to no helper at all; each reads
`self.<field>.strip()` behind an `is not None` test and each answered `500` over
HTTP while this module reported the codebase compliant. An optional field is
*more* prone to the shape, not less, because `if self.x is not None and not
self.x.strip()` reads as a guarded access and is not one.

Three further ways past it were planted and all three now redden: the helper
extraction above, a check placed after the read inside one statement, and a
local `def` shadowing the name of a helper measured at module scope.

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
        keywords: dict[str, Any] = {}
        synthesised = True
        for parameter in parameters[1:]:
            if parameter.default is not inspect.Parameter.empty:
                continue
            annotation = str(parameter.annotation)
            # Enough shapes to reach every helper `commands.py` actually has.
            # The first version stopped at two and silently skipped four --
            # including `_goodnotes_id` and `_bounded_token`, which *do*
            # type-check, so their callers were reported unguarded once the
            # population widened. A helper this cannot synthesise is skipped and
            # its callers stay in the population, which is the safe direction,
            # but skipping one that guards is a false positive that trains a
            # reader to ignore the module.
            if "SafeDetail" in annotation:
                value: Any = SafeDetail.QUERY
            elif "IdKind" in annotation:
                value = None
            elif annotation.startswith("int"):
                value = 1
            elif annotation.startswith("str"):
                value = "x"
            elif "frozenset" in annotation or "set[" in annotation:
                value = frozenset()
            else:
                synthesised = False
                break
            if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
                keywords[parameter.name] = value
            else:
                arguments.append(value)
        if not synthesised:
            continue
        try:
            helper(*arguments, **keywords)
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


def _string_fields(node: ast.ClassDef) -> tuple[str, ...]:
    """Fields whose value, when present, is a `str` — `str` and `str | None`.

    **`str | None` was excluded, and the exclusion was justified by a claim that
    is false.** The first version of this module said those fields "are guarded
    by `_identifier`, `_positive`, `_moment` and their siblings, which
    type-check what they are handed". The tenth review checked: `UpdateTask.title`,
    `TransitionTask.closure_evidence_ref` and `DecideReviewCase.corrected_value`
    are handed to no helper at all. Each reads `self.<field>.strip()` behind an
    `is not None` test, which is precisely the construct this module exists to
    forbid, and each answered `500` over HTTP while this module reported the
    codebase compliant.

    An optional field is *more* likely to carry this shape, not less, because
    `if self.x is not None and not self.x.strip()` reads as a guarded access and
    is not one. `None` is excluded from the union and everything else must be a
    string, so the rule is the same rule.
    """
    fields: list[str] = []
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign) or statement.annotation is None:
            continue
        target = statement.target
        if not isinstance(target, ast.Name):
            continue
        parts = {part.strip() for part in ast.unparse(statement.annotation).split("|")} - {"None"}
        if parts != {"str"}:
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


def _at(node: ast.AST) -> tuple[int, int]:
    """Source position, so order is compared where it is actually decided.

    The first version compared *top-level statement index*, so a check and a
    read inside one statement always passed regardless of which came first —
    while the docstring claimed "presence is not enough". The tenth review
    planted `if not self.query.strip() or not isinstance(self.query, str):`,
    which reads before it checks, and the module stayed green over a live
    `AttributeError`.
    """
    return (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))


def _rebound_inside(body: ast.FunctionDef) -> frozenset[str]:
    """Names assigned within `__post_init__`, which therefore are not the helper.

    `_GUARDING` is a set of module-level function names measured by calling
    them. Crediting a call by name assumes the name still resolves to what was
    measured. A local `def _text(...)` or `_text = lambda ...` inside
    `__post_init__` shadows it, and the tenth review used exactly that to keep
    this module green over a field that was never type-checked.
    """
    rebound: set[str] = set()
    for inner in ast.walk(body):
        if isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef) and inner is not body:
            rebound.add(inner.name)
        elif isinstance(inner, ast.Assign):
            rebound.update(target.id for target in inner.targets if isinstance(target, ast.Name))
        elif isinstance(inner, ast.AnnAssign) and isinstance(inner.target, ast.Name):
            rebound.add(inner.target.id)
    return frozenset(rebound)


def _bound_locals(body: ast.FunctionDef, field: str) -> frozenset[str]:
    """Locals that hold the field's value, so a read through one still counts.

    `value = self.query` followed by `value.strip()` dereferences the field
    under another name. The eleventh review planted exactly that and the module
    stayed green over a live `AttributeError`. Tracked in both directions: a
    check written against the local (`isinstance(value, str)`) counts too, so
    the rule does not fire on code that is genuinely safe.
    """
    held: set[str] = set()
    for inner in ast.walk(body):
        if not isinstance(inner, ast.Assign) or not _names_the_field(inner.value, field):
            continue
        held.update(target.id for target in inner.targets if isinstance(target, ast.Name))
    return frozenset(held)


def _names_it(node: ast.expr, field: str, locals_: frozenset[str]) -> bool:
    """`self.<field>`, or a local holding it."""
    return _names_the_field(node, field) or (isinstance(node, ast.Name) and node.id in locals_)


def _reads(body: ast.FunctionDef, field: str, rebound: frozenset[str]) -> list[tuple[int, int]]:
    """Every position at which the field's value is used as a string.

    Two shapes, not one. A direct `self.<field>.<attr>` is the obvious one. The
    other is `helper(self.<field>, …)` where the helper is **not** one measured
    to type-check: the tenth review extracted the read into a module-level
    `_squeeze(value, detail)` that calls `value.strip()`, which removed the
    field from the population entirely — `commands.py` already does exactly that
    five times over, so the shape is idiomatic rather than contrived.
    """
    locals_ = _bound_locals(body, field)
    positions: list[tuple[int, int]] = []
    for inner in ast.walk(body):
        if isinstance(inner, ast.Attribute) and _names_it(inner.value, field, locals_):
            positions.append(_at(inner))
        elif isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
            named = inner.func.id
            if named == "isinstance" or named in rebound:
                continue
            if named in _GUARDING:
                continue
            if any(_names_it(argument, field, locals_) for argument in inner.args):
                positions.append(_at(inner))
    return positions


def _checks(body: ast.FunctionDef, field: str, rebound: frozenset[str]) -> list[tuple[int, int]]:
    """Every position at which the field's type is established."""
    locals_ = _bound_locals(body, field)
    positions: list[tuple[int, int]] = []
    for inner in ast.walk(body):
        if not isinstance(inner, ast.Call) or not isinstance(inner.func, ast.Name):
            continue
        if inner.func.id in rebound:
            continue
        if inner.func.id == "isinstance":
            if len(inner.args) != 2:
                continue
            subject, kind = inner.args
            if _names_it(subject, field, locals_) and "str" in ast.unparse(kind):
                positions.append(_at(inner))
            continue
        if inner.func.id in _GUARDING and inner.args and _names_it(inner.args[0], field, locals_):
            positions.append(_at(inner))
    return positions


def _commands() -> tuple[ast.ClassDef, ...]:
    return tuple(
        node for node in _module().body if isinstance(node, ast.ClassDef) and _is_command(node)
    )


def _unguarded() -> tuple[tuple[str, str], ...]:
    """Every (command, field) whose value is used as a string before its type is known."""
    offences: list[tuple[str, str]] = []
    for node in _commands():
        body = _post_init(node)
        if body is None:
            continue
        rebound = _rebound_inside(body)
        for field in _string_fields(node):
            reads = _reads(body, field, rebound)
            if not reads:
                continue
            checks = _checks(body, field, rebound)
            if not checks or min(checks) > min(reads):
                offences.append((node.name, field))
    return tuple(offences)


#: Offending pairs that predate this branch, each with the capability it reaches.
#:
#: **A shrinking allowlist, not an exemption list.** Every entry is asserted
#: below to still be an offence, so a fixed one reddens and has to be removed —
#: the shape `ALLOWED` and `EXCUSED` use elsewhere in this tier. Nothing may be
#: added to it without the same provenance check that put these here.
#:
#: Measured, not assumed: this module run against `git show main:…/commands.py`
#: reports **fourteen** offending pairs, and every entry below is among them.
#: This branch removed five (`CreateTask` twice, `CreateCommitment` twice,
#: `CloseCommitment`) and introduced none. They are recorded rather than fixed
#: because they reach `tasks.*`, `review.*`, `continuity.*`, `documents.*` and
#: `context.prepare` — none of them the relationship-intelligence plane this
#: branch delivers — and widening a 224-file pull request to carry them was
#: declined deliberately rather than overlooked.
#:
#: What each costs today: the first three answer `500 internal_error` over HTTP
#: for a non-string in the named field, because the field is dereferenced. The
#: `idempotency_key` and `conversation_context` entries route through
#: `_idempotency_key`, which tests truthiness and never the type, so a
#: non-string is *accepted* and reaches a handler that assumes a string.
CARRIED_FROM_THE_MERGE_BASE: tuple[tuple[str, str, str], ...] = (
    ("UpdateTask", "title", "tasks.update"),
    ("TransitionTask", "closure_evidence_ref", "tasks.transition"),
    ("DecideReviewCase", "corrected_value", "review.decide"),
    ("CreateProject", "idempotency_key", "continuity.projects.create"),
    ("CreateSituation", "idempotency_key", "continuity.situations.create"),
    ("RecordTask", "idempotency_key", "continuity.tasks.create"),
    ("CreateManagedDocument", "idempotency_key", "documents.create"),
    ("ReviseManagedDocument", "idempotency_key", "documents.revise"),
    ("PrepareContext", "conversation_context", "context.prepare"),
)

_CARRIED: frozenset[tuple[str, str]] = frozenset(
    (command, field) for command, field, _ in CARRIED_FROM_THE_MERGE_BASE
)


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
        for field in _string_fields(node)
        if _dereferences(_post_init(node), field)  # type: ignore[arg-type]
    ]
    assert len(read) >= 8, f"only {len(read)} dereferenced string fields parsed"


@pytest.mark.parametrize(
    "command",
    [node.name for node in _commands()],
)
def test_every_command_checks_a_string_field_before_reading_it(command: str) -> None:
    """Per command, so a failure names the one that regressed."""
    offending = [
        field for name, field in _unguarded() if name == command and (name, field) not in _CARRIED
    ]
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
    assert sorted(pair for pair in _unguarded() if pair not in _CARRIED) == []


def test_every_carried_entry_is_still_an_offence() -> None:
    """The allowlist shrinks or reddens; it cannot rot into a list of excuses.

    An entry that has been fixed fails here and has to be deleted. That is the
    only direction this list is allowed to move without the provenance check
    that built it.
    """
    live = set(_unguarded())
    fixed = sorted(pair for pair in _CARRIED if pair not in live)
    assert fixed == [], (
        f"{fixed} no longer read a string field before checking it. Remove them "
        f"from CARRIED_FROM_THE_MERGE_BASE rather than leaving the list to rot."
    )


def test_every_carried_entry_names_the_capability_it_actually_reaches() -> None:
    """The third column is derived, not taken on trust.

    It was read straight out of the tuple, so the test below could be switched
    off by mistyping one string. The eleventh review did exactly that: adding a
    fabricated entity-plane entry labelled `"tasks.update"` passed, and the same
    entry labelled honestly reddened. A label nobody checks is not a label.
    """
    wrong = sorted(
        f"{command} says {capability!r}, declares "
        f"{getattr(commands_module, command).capability.value!r}"
        for command, _, capability in CARRIED_FROM_THE_MERGE_BASE
        if getattr(commands_module, command).capability.value != capability
    )
    assert wrong == []


def test_nothing_on_the_entity_plane_is_carried() -> None:
    """This branch's own surface has to be clean, allowlist or no allowlist.

    The allowlist exists to bound a pull request, not to let this branch carry
    its own instance of the defect. A future `entities.*` command appearing here
    means the exemption is being used for something it was not granted for.

    Read from the command's own `capability` `ClassVar` rather than from the
    tuple's third column, so this cannot be turned off by writing a different
    string; the column is checked against the same source above.
    """
    theirs = sorted(
        f"{command}.{field}"
        for command, field, _ in CARRIED_FROM_THE_MERGE_BASE
        if getattr(commands_module, command).capability.value.startswith("entities.")
    )
    assert theirs == []
