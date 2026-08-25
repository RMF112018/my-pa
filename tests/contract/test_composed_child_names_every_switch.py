"""The all-capability child process is given every switch that withholds a capability.

`tests/contract/test_mcp_transport.py::test_a_child_with_a_managed_root_publishes_every_capability`
is the only place in this repository where a **real** composition root is started
with everything turned on and asked to publish the whole capability set. Its
claim -- "every capability" -- holds only if the environment it hands the child
turns on every switch `ApplicationService.available_capabilities` subtracts on.

That list was written out by hand, and Phase B broke it: a fourth relationship
switch was added, `available_capabilities` grew a fourth subtraction, and the
child's environment was not extended. The child composed without the
identity-correction plane and published ninety-seven of ninety-nine names while
asserting it published all of them -- and the assertion still passed, because
the *expected* value is derived from `Capability` but the *actual* value comes
from a process that was never told to serve them. What made the miss survive is
that the test is `@pytest.mark.database`, so the FAST tier every commit was
gated on structurally could not see it; the only tier that could ran once, at
the end of the phase.

This module is the guard that was missing. It does not start a process and it
is not marked `database`, so it runs in FAST on every commit. It derives the
switch set from `available_capabilities` itself -- by reading which instance
attributes that property branches on -- resolves each one to the constructor
keyword that supplies it, resolves that to the `Settings` field of the same
name, and asserts the child's environment names the corresponding
`MY_PA_...` variable. A fifth switch therefore joins this claim by being
written, not by somebody remembering to extend a list.

The derivation is asserted non-empty and its size is spelled, so that a
refactor which stops `available_capabilities` reading `self.` attributes --
folding the branches into a helper, say -- fails here rather than silently
turning this module into a test of nothing.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Final

import pytest

from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import ENV_PREFIX, Settings

#: The one attribute `available_capabilities` branches on that is not a boolean
#: switch: it is the composed byte store itself, which is `None` when no managed
#: root was configured. It reaches the constructor as `managed_store`, which is
#: not a `Settings` field, so the name-for-name derivation below cannot resolve
#: it and it is checked on its own instead -- the child must still be given a
#: managed root, and `_MANAGED_ROOT_VARIABLE` is what that looks like in the
#: environment. Named here with its reason rather than skipped silently.
_COMPOSED_DEPENDENCY_ATTRIBUTES: Final[frozenset[str]] = frozenset({"_managed_store_or_none"})

_MANAGED_ROOT_VARIABLE: Final = f"{ENV_PREFIX}MANAGED_DOCUMENT_ROOT"

#: The module and function whose environment is under audit.
_TRANSPORT_TEST_PATH: Final = Path(__file__).with_name("test_mcp_transport.py")
_TRANSPORT_TEST_NAME: Final = "test_a_child_with_a_managed_root_publishes_every_capability"


def _service_tree() -> ast.Module:
    return ast.parse(inspect.getsource(inspect.getmodule(ApplicationService)))


def _class_body(tree: ast.Module) -> list[ast.stmt]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ApplicationService":
            return node.body
    raise AssertionError("ApplicationService is not a class in its own module")


def _function(body: list[ast.stmt], name: str) -> ast.FunctionDef:
    for node in body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"ApplicationService has no `{name}`")


def _attributes_read_by_available_capabilities() -> frozenset[str]:
    """Every `self._x` the published-surface property reads."""
    body = _class_body(_service_tree())
    return frozenset(
        node.attr
        for node in ast.walk(_function(body, "available_capabilities"))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def _constructor_keyword_for(attributes: frozenset[str]) -> dict[str, str]:
    """`self._x = x` in `__init__`, read back as attribute -> keyword."""
    initializer = _function(_class_body(_service_tree()), "__init__")
    keywords: dict[str, str] = {}
    for node in ast.walk(initializer):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr in attributes
            and isinstance(node.value, ast.Name)
        ):
            keywords[target.attr] = node.value.id
    return keywords


def _environment_names_in_the_transport_test() -> dict[str, str]:
    """The keyword arguments `test_a_child_...` hands `_child_tool_list`."""
    tree = ast.parse(_TRANSPORT_TEST_PATH.read_text(encoding="utf-8"))
    target = _function(tree.body, _TRANSPORT_TEST_NAME)
    for node in ast.walk(target):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_child_tool_list"
        ):
            return {
                keyword.arg: (
                    keyword.value.value if isinstance(keyword.value, ast.Constant) else "<expr>"
                )
                for keyword in node.keywords
                if keyword.arg is not None
            }
    raise AssertionError(f"`{_TRANSPORT_TEST_NAME}` no longer spawns a child")


def _switch_variables() -> dict[str, str]:
    """Environment variable -> the `Settings` field it sets, for every switch."""
    attributes = _attributes_read_by_available_capabilities() - _COMPOSED_DEPENDENCY_ATTRIBUTES
    keywords = _constructor_keyword_for(attributes)
    assert set(keywords) == attributes, (
        "an attribute the published surface branches on is not assigned from a "
        f"constructor keyword of its own: {sorted(attributes - set(keywords))}"
    )
    variables: dict[str, str] = {}
    for keyword in keywords.values():
        assert keyword in Settings.model_fields, (
            f"`{keyword}` narrows the published surface but is not a Settings field, "
            "so no operator can set it and this guard cannot name its variable"
        )
        variables[f"{ENV_PREFIX}{keyword.upper()}"] = keyword
    return variables


def test_the_derivation_finds_the_switches_the_published_surface_branches_on() -> None:
    """The guard is asserted to have found something, and how much.

    Both halves matter. An empty derivation would make every claim below vacuous.
    A *shrinking* derivation -- `available_capabilities` refactored so its
    branches move behind a helper and it reads no `self._` flag directly -- would
    be the same failure wearing a different shape, so the count is spelled.
    """
    variables = _switch_variables()
    assert variables, "no switch narrows the published surface, so this module proves nothing"
    assert len(variables) == 4, (
        "the published surface is narrowed by a different number of switches than "
        f"this guard knows about: {sorted(variables)}"
    )
    assert set(variables.values()) == {
        "relationship_intelligence_enabled",
        "relationship_intelligence_writes_enabled",
        "relationship_memory_enabled",
        "relationship_identity_correction_enabled",
    }


def test_every_switch_is_a_boolean_an_operator_can_set() -> None:
    """A switch that is not a flag would not be turned on by `"true"` in the child."""
    for variable, field in _switch_variables().items():
        assert Settings.model_fields[field].annotation is bool, (
            f"{variable} narrows the published surface but is not a boolean setting"
        )
        assert Settings.model_fields[field].default is False, (
            f"{variable} narrows the published surface and does not default off, so a "
            "process nobody configured would serve it"
        )


def test_the_all_capability_child_is_given_every_switch() -> None:
    """The claim this module exists for.

    `test_a_child_with_a_managed_root_publishes_every_capability` asserts the
    child publishes the whole of `Capability`. That is only a statement about
    the child if the child was composed for the whole of it.
    """
    handed = _environment_names_in_the_transport_test()
    missing = sorted(variable for variable in _switch_variables() if variable not in handed)
    assert not missing, (
        f"`{_TRANSPORT_TEST_NAME}` claims a child publishes every capability while "
        f"withholding the switch(es) that serve some of them: {missing}"
    )


def test_every_switch_the_child_is_given_is_actually_turned_on() -> None:
    """Naming a variable is not setting it: `"false"` would compose the same gap."""
    handed = _environment_names_in_the_transport_test()
    for variable in _switch_variables():
        assert handed[variable] == "true", (
            f"{variable} is handed to the all-capability child as {handed[variable]!r}, "
            "so the child is not composed for the surface the test claims it publishes"
        )


def test_the_child_is_also_given_the_managed_root_and_a_database(tmp_path: Path) -> None:
    """The two composed dependencies that are not flags, checked on their own.

    `_managed_store_or_none` is excluded from the name-for-name derivation
    because it reaches the constructor as an object rather than as a setting, so
    it would otherwise leave the surface it withholds unguarded. The database URL
    is here for the same reason: composing the byte store reads the configured
    source roots, which is why that test is marked `database` at all, and a child
    handed no reachable server would refuse to start rather than publish anything.
    """
    assert _attributes_read_by_available_capabilities() >= _COMPOSED_DEPENDENCY_ATTRIBUTES, (
        "the excused attribute is no longer read by the published-surface property, "
        "so the excuse is stale and should be deleted rather than carried"
    )
    handed = _environment_names_in_the_transport_test()
    assert _MANAGED_ROOT_VARIABLE in handed
    assert f"{ENV_PREFIX}DATABASE_URL" in handed


@pytest.mark.parametrize("switch", sorted(_switch_variables()))
def test_a_switch_would_be_noticed_missing(switch: str) -> None:
    """The control: the guard reads the real call, so removing one is visible.

    Parametrised over the derivation so the negative case grows with it. The
    mutation is applied to the *reading*, not to the file: the environment the
    transport test hands its child, minus one variable, is what the guard would
    have been given had somebody forgotten that one -- and the assertion the
    guard makes about it must fail.
    """
    handed = dict(_environment_names_in_the_transport_test())
    del handed[switch]
    missing = sorted(variable for variable in _switch_variables() if variable not in handed)
    assert missing == [switch]
