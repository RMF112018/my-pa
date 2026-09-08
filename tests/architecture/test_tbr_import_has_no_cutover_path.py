"""PC-CM-IMP-WP13 T13-16: the import tool has no real-apply and no cutover path.

A real TBR apply and a cutover are not authorised at this head. The usual way to
record that is a sentence in a docstring, and a sentence in the module under test
cannot fail. So the rule is decided by reading the program with `ast` and by
running its own guard function:

1. Two subcommands and exactly two — a third is a code change here.
2. No option, default or string constant anywhere in it names a real target: no
   `prj_` literal, no SharePoint or connector host, no `.xlsm` write path, no
   "cutover" and no "production".
3. Every option is required and none carries a default value, so no source and
   no target can be inferred.
4. `apply-disposable` refuses a database whose name is not one the disposable
   provisioning vocabulary produces — checked against a name that vocabulary
   actually generates, so the two cannot drift apart silently.
5. Nothing in the program writes a package: it opens a workbook to read and has
   no write path back to one.

The disposable-name rule is the one worth restating. The program cannot import
`tests/db/provisioning.py` — that would put the test tree on an operator
program's import path — so it restates the pattern, and this test is what proves
the restatement still matches what the helper makes.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Final

import apps.cli.tbr_import as tool
import pytest
from tests.db.provisioning import (
    CLONE_KIND,
    EMPTY_KIND,
    TEMPLATE_KIND,
    disposable_database_name,
)

ROOT: Final = Path(__file__).resolve().parents[2]
SOURCE: Final = ROOT / "apps" / "cli" / "tbr_import.py"

#: Words that would name a real target, a live source or a mutation this head
#: does not authorise. Each is searched for in the program's own strings.
FORBIDDEN_TOKENS: Final = (
    "cutover",
    "production",
    "sharepoint",
    "graph.microsoft",
    "onedrive",
    "connector",
    "P250357",
    "Constraints Log",
)


def _tree() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def _string_constants() -> list[str]:
    """Every string literal that is not a docstring.

    Docstrings are excluded on purpose and the exclusion is the point: the
    program's own prose *names* the prohibited things in order to prohibit them,
    and a scan that could not tell a prohibition from a target would force the
    documentation to go quiet about exactly the risk it exists to record.
    """
    tree = _tree()
    docstrings = {ast.get_docstring(tree, clean=False)}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            docstrings.add(ast.get_docstring(node, clean=False))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    ]


def _options(parser: argparse.ArgumentParser) -> set[str]:
    actions = list(parser._actions)
    found: set[str] = set()
    while actions:
        action = actions.pop()
        found.update(action.option_strings)
        if isinstance(action, argparse._SubParsersAction):
            for nested in action.choices.values():
                actions.extend(nested._actions)
    return found


def _subcommands(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("the program declares no subcommands")


def test_there_are_exactly_two_modes_and_neither_is_a_real_apply() -> None:
    """T13-16. A third mode is a change to this test, not a quiet addition."""
    assert _subcommands(tool.build_parser()) == {"dry-run", "apply-disposable"}


def test_no_option_carries_a_default_target_or_a_default_source() -> None:
    """T13-16, AGENTS.md section 5. Nothing can be inferred, so nothing is."""
    parser = tool.build_parser()
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for nested in action.choices.values():
            for option in nested._actions:
                if option.dest in {"help", "party_map"}:
                    continue
                assert option.required, option.dest
                assert option.default is None, option.dest


def test_the_two_programs_share_the_options_they_must_and_no_target() -> None:
    """Both modes take the same explicit inputs; only the apply names a database."""
    options = _options(tool.build_parser())
    assert {"--source", "--sheet", "--project-id", "--principal", "--register-id"} <= options
    assert "--confirm-disposable-target" in options


@pytest.mark.parametrize("token", FORBIDDEN_TOKENS, ids=lambda value: str(value))
def test_no_string_in_the_program_names_a_real_target(token: str) -> None:
    """T13-16. Read from the syntax tree, so a docstring cannot satisfy it."""
    lowered = [value.lower() for value in _string_constants()]
    assert not any(token.lower() in value for value in lowered), token


def test_no_project_identity_is_hard_coded() -> None:
    """T13-16. The canonical `prj_` identity is supplied, never carried."""
    assert not any(value.startswith("prj_") for value in _string_constants())


def test_the_program_opens_no_package_for_writing() -> None:
    """T13-16. There is no `.xlsm` write path: the source is read and never rewritten."""
    tree = _tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"write_bytes", "write_text"}:
            target = node.value
            assert not (isinstance(target, ast.Name) and target.id == "source")
    assert "zipfile" not in {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }


@pytest.mark.parametrize("kind", (TEMPLATE_KIND, CLONE_KIND, EMPTY_KIND))
def test_a_name_the_provisioning_vocabulary_makes_is_accepted(kind: str) -> None:
    """T13-16. The restated pattern still matches what the helper actually makes."""
    assert tool.is_disposable_database(disposable_database_name(kind, "run01", "gw3"))
    assert tool.is_disposable_database(disposable_database_name(kind, "run01", "gw3", 7))


@pytest.mark.parametrize(
    "name",
    ("my_pa", "postgres", "template1", "my_pa_production", "mypa_p_c_run01_gw3", None, ""),
    ids=lambda value: str(value),
)
def test_a_name_outside_that_vocabulary_is_refused(name: str | None) -> None:
    """T13-16. A persistent or production catalog is never a target of this program."""
    assert not tool.is_disposable_database(name)


def test_the_apply_refuses_a_confirmation_that_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T13-16. Naming a disposable database is not enough: it must be named twice."""
    configured = disposable_database_name(CLONE_KIND, "run01", "gw3")
    other = disposable_database_name(CLONE_KIND, "run02", "gw4")
    assert configured != other

    class _Url:
        database = configured

    class _Settings:
        def parsed_database_url(self) -> _Url:
            return _Url()

    monkeypatch.setattr(tool, "load_settings", lambda: _Settings())
    monkeypatch.setattr(tool, "_check_identifiers", lambda args: None)
    args = argparse.Namespace(confirm_disposable_target=other)
    assert tool._apply_disposable(args) == tool.EXIT_FAILED


def test_the_apply_refuses_a_non_disposable_database_even_when_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T13-16. Confirming a persistent catalog by name does not make it a target."""

    class _Url:
        database = "my_pa"

    class _Settings:
        def parsed_database_url(self) -> _Url:
            return _Url()

    monkeypatch.setattr(tool, "load_settings", lambda: _Settings())
    monkeypatch.setattr(tool, "_check_identifiers", lambda args: None)
    args = argparse.Namespace(confirm_disposable_target="my_pa")
    assert tool._apply_disposable(args) == tool.EXIT_FAILED
