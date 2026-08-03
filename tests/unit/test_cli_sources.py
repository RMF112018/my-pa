"""The source-registration command as a parser and as an output surface.

No database. What is checked here is the shape an operator meets — which
subcommands exist, which options each takes, which values they accept — and one
property that is worth more than all of them: **no print path echoes the root**.

The last is asserted by reading the module with `ast` rather than by running it,
because the interesting paths are the failure paths and a test that only ran the
successful one would prove the least interesting case. `migration.py` set the
rule — it prints `source_sha256` and `source_bytes` and never the `--source`
path — and a configured root is the same kind of value: an operator's directory
layout, on a terminal, in a shell history, and in whatever evidence file the
output was redirected to.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

import apps.cli.sources as command
import pytest

from my_pa.domain.common.classification import Classification
from my_pa.domain.source.registry import SourceProviderKind

MODULE = Path(command.__file__)

#: Identifiers that hold, or could hold, the configured root. `root` is the
#: resolved `Path` and the parser's own destination; `native_root` is the column
#: it is stored in and the keyword `register_source` takes it under.
ROOT_BEARING = frozenset({"root", "native_root"})


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    """The subcommand parsers, by name."""
    found: dict[str, argparse.ArgumentParser] = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            found.update(action.choices)
    return found


def _options(parser: argparse.ArgumentParser) -> set[str]:
    return {
        option
        for action in parser._actions
        for option in action.option_strings
        if option not in {"-h", "--help"}
    }


def _print_calls() -> list[ast.Call]:
    """Every `print(...)` in the command, wherever it appears."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]


def _identifiers(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name):
            found.add(inner.id)
        elif isinstance(inner, ast.Attribute):
            found.add(inner.attr)
    return found


# ---- the parser ---------------------------------------------------------------


def test_the_command_offers_exactly_two_subcommands() -> None:
    """Register and list, and nothing that could act on what was registered.

    A third subcommand is not forbidden by anything mechanical, so this is where
    one would be noticed: `enroll`, `read`, or `fetch` here would be a capability
    wearing an operator command's clothes.
    """
    assert set(_subparsers(command.build_parser())) == {"register", "list"}


def test_register_takes_four_options_and_every_one_is_required() -> None:
    """Nothing is inferred. `AGENTS.md` section 5: operator scripts name targets."""
    register = _subparsers(command.build_parser())["register"]
    assert _options(register) == {"--provider", "--root", "--label", "--classification"}
    required = {
        option
        for action in register._actions
        for option in action.option_strings
        if action.required
    }
    assert required == {"--provider", "--root", "--label", "--classification"}


def test_the_closed_choices_are_the_domain_enums_and_not_a_second_list() -> None:
    """Two option surfaces, both driven by the enum rather than by a literal.

    A hand-written list here would be a second declaration of the same closed
    set, and adding a provider kind or a classification would leave the CLI
    silently refusing a value the domain accepts.
    """
    register = _subparsers(command.build_parser())["register"]
    choices = {
        action.dest: set(action.choices or ())
        for action in register._actions
        if action.choices is not None
    }
    assert choices["provider"] == {kind.value for kind in SourceProviderKind}
    assert choices["classification"] == {value.value for value in Classification}
    assert choices["provider"] and choices["classification"]


def test_a_parsed_registration_carries_every_value_it_was_given() -> None:
    """The parser is wired, not merely declared."""
    args = command.build_parser().parse_args(
        [
            "register",
            "--provider",
            "fixture",
            "--root",
            "fixtures/mcv/root",
            "--label",
            "MCV fixture corpus",
            "--classification",
            "synthetic_test",
        ]
    )
    assert args.command == "register"
    assert args.provider == "fixture"
    assert args.root == Path("fixtures/mcv/root")
    assert args.label == "MCV fixture corpus"
    assert args.classification == "synthetic_test"


def test_listing_needs_nothing_and_says_so() -> None:
    """`list` takes no option, because there is nothing to scope it by."""
    parser = command.build_parser()
    assert _options(_subparsers(parser)["list"]) == set()
    assert parser.parse_args(["list"]).command == "list"


def test_a_registration_missing_its_root_is_refused_by_the_parser() -> None:
    """Argparse exits `2` rather than the command running with a root it invented."""
    with pytest.raises(SystemExit) as exited:
        command.build_parser().parse_args(
            [
                "register",
                "--provider",
                "fixture",
                "--label",
                "x",
                "--classification",
                "synthetic_test",
            ]
        )
    assert exited.value.code == 2


# ---- no path is echoed --------------------------------------------------------


def test_the_command_prints_something_on_both_paths() -> None:
    """Guard the rule below: a module with no `print` would satisfy it vacuously."""
    calls = _print_calls()
    assert len(calls) >= 7, f"only {len(calls)} print calls found; the rule below decides nothing"


def test_no_print_path_echoes_the_configured_root() -> None:
    """Every `print` in the module, including the refusals.

    Read from the source, so the failure paths are covered as thoroughly as the
    successful one — including the `OSError` path, whose exception renders with
    the filename it failed on and whose text is therefore deliberately not
    printed.
    """
    offending = [ast.unparse(call) for call in _print_calls() if _identifiers(call) & ROOT_BEARING]
    assert not offending, f"these print paths carry the configured root: {offending}"


def test_the_root_rule_catches_a_planted_echo() -> None:
    """The rule fires on the four shapes an echo would actually take."""
    planted = [
        "print(root)",
        "print(f'root {root}')",
        "print(args.root)",
        "print(f'{source.native_root}')",
    ]
    for statement in planted:
        call = ast.parse(statement).body[0]
        assert isinstance(call, ast.Expr) and isinstance(call.value, ast.Call)
        assert _identifiers(call.value) & ROOT_BEARING, f"{statement!r} escaped the root rule"


def test_the_root_rule_permits_the_label_it_is_meant_to_permit() -> None:
    """Narrow, and shown to be: the printed field *names* the root and is not it.

    Without this, a rule that matched the string `root` anywhere would flag
    `root_object_id` — the one value the command exists to hand back — and the
    honest response to that failure would have been to stop printing it.
    """
    call = ast.parse("print(f'root_object_id   {observed.source_object_id}')").body[0]
    assert isinstance(call, ast.Expr) and isinstance(call.value, ast.Call)
    assert not _identifiers(call.value) & ROOT_BEARING
