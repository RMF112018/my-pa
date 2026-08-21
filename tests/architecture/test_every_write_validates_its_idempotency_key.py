"""A write validates its idempotency key by calling the helper, not by retyping it.

`_idempotency_key` existed and tested truthiness rather than type, so a
non-string key was accepted into handlers that go on to use it as one. Fixing
the helper fixed the five commands that called it. It fixed none of the ten
that spelled `if not self.idempotency_key:` inline instead — the same rule,
written out ten times, each copy free to drift and none of them reached by a
change to the helper they were copied from.

That is the shape this tier keeps finding: a rule applied where a reviewer
pointed rather than to the population it names. The eleventh review of the
entity-plane branch swept 620 field combinations to discover those ten, and
recorded them as "outside the guard's stated rule" — true, and the reason the
count in the record was wrong rather than the guard being wrong.

So the rule is stated over the population directly. Every command carrying an
`idempotency_key` field must hand it to `_idempotency_key`. The population is
derived from the dataclass fields, so a command added tomorrow is in it without
anyone remembering to add it here, and an inline re-spelling of the check is
red on arrival rather than after the next sweep.

**Why not just assert the behaviour.** A behavioural test needs a valid
instance of each command, and eighteen of the forty-three cannot be built
without command-specific knowledge of what their other fields accept. A test
that silently covers twenty-five of forty-three reads as coverage and is not.
This reads every command, builds none, and skips nothing.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest

from my_pa.application import commands as commands_module

_SOURCE = Path(inspect.getfile(commands_module))
_FIELD = "idempotency_key"
_HELPER = "_idempotency_key"


def _commands_carrying_a_key() -> tuple[type, ...]:
    """Every command dataclass with an `idempotency_key` field, derived not listed."""
    found = []
    for name in dir(commands_module):
        candidate = getattr(commands_module, name)
        if not isinstance(candidate, type) or not dataclasses.is_dataclass(candidate):
            continue
        if not hasattr(candidate, "capability"):
            continue
        if any(field.name == _FIELD for field in dataclasses.fields(candidate)):
            found.append(candidate)
    return tuple(found)


def _post_init(name: str) -> ast.FunctionDef | None:
    tree = ast.parse(_SOURCE.read_text())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            for statement in node.body:
                if isinstance(statement, ast.FunctionDef) and statement.name == "__post_init__":
                    return statement
    return None


def test_the_population_this_module_reads_is_not_empty() -> None:
    """An anti-vacuity floor, for the reason its sibling module states.

    If `capability` were renamed, or the field spelled differently, every
    assertion below would pass over an empty set and report the codebase
    compliant. The floor sits far below the current figure so ordinary
    additions do not touch it, and far above zero so a broken reader does.
    """
    found = _commands_carrying_a_key()
    assert len(found) >= 12, f"only {len(found)} commands with {_FIELD} parsed from {_SOURCE}"


@pytest.mark.parametrize(
    "command",
    [command.__name__ for command in _commands_carrying_a_key()],
)
def test_every_write_hands_its_idempotency_key_to_the_helper(command: str) -> None:
    """Per command, so a failure names the one that re-spelled the check."""
    body = _post_init(command)
    assert body is not None, f"{command} carries {_FIELD} and validates nothing"

    handed_over = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == _HELPER
        and node.args
        and isinstance(node.args[0], ast.Attribute)
        and node.args[0].attr == _FIELD
        for node in ast.walk(body)
    )
    assert handed_over, (
        f"{command}.__post_init__ does not call {_HELPER}(self.{_FIELD}). "
        f"An inline `if not self.{_FIELD}:` tests truthiness and never the type, "
        f"so a non-string key is accepted and reaches a handler that assumes a "
        f"string — and a later fix to {_HELPER} does not reach this copy."
    )
