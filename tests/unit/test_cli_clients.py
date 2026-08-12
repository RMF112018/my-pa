"""The client-registration command as a parser and as an output surface.

No database. What is checked here is the shape an operator meets and two
properties worth more than the shape:

* **there is no way to ask for a client bound to somebody else.** The absence of
  a `--principal-id` option is asserted rather than described, because an option
  naming the Principal a credential acts for would be caller-supplied identity
  with a longer lifetime than any request;
* **the secret is printed once, by one function.** Asserted by reading the module
  with `ast`, so it holds for the failure paths too — a test that only ran the
  successful one would prove the least interesting case. `sources.py` set the
  pattern for reading a command this way, and for the same reason.

The digest is asserted to reach no print path at all. It is not a credential, but
printing it beside the credential is how a reader comes to believe one of them is
storable.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

import apps.cli.clients as command
import pytest

from my_pa.adapters.http import REMOTE_CAPTURE_PATH
from my_pa.bootstrap.settings import AuthMode, Settings

MODULE = Path(command.__file__)

DSN = "postgresql+psycopg://my_pa@localhost:5433/my_pa_cli_clients_probe"

#: Names that hold a secret or its digest. Neither may reach a print path except
#: the one deliberate disclosure `register` performs.
SECRET_BEARING = frozenset({"digest", "secret_sha256"})


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
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


def _tree() -> ast.Module:
    return ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))


def _print_calls_by_function() -> dict[str, list[ast.Call]]:
    """Every `print(...)`, keyed by the function it appears in."""
    found: dict[str, list[ast.Call]] = {}
    for function in ast.walk(_tree()):
        if not isinstance(function, ast.FunctionDef):
            continue
        found[function.name] = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ]
    return found


def test_the_command_offers_the_four_operator_actions() -> None:
    """Mint, list, revoke, and observe. Nothing that serves a request."""
    assert set(_subparsers(command.build_parser())) == {"register", "revoke", "list", "status"}


def test_no_subcommand_takes_a_principal_identifier() -> None:
    """The binding is the mode's, not the operator's.

    A `--principal-id` option would let a shell mint a credential acting for a
    Principal the process never authenticated — caller-supplied identity that
    outlives the call that supplied it, which is exactly what `D-13`/`D-14` keep
    out of this tree. Its absence is structural and is asserted here so that
    adding one is a test failure rather than a convenience.
    """
    parser = command.build_parser()
    every = _options(parser) | {
        option for sub in _subparsers(parser).values() for option in _options(sub)
    }
    assert every == {"--client-id"}, (
        f"the command offers {sorted(every)}; only `--client-id` names anything, "
        "and it names a client rather than a Principal"
    )


def test_only_registration_prints_a_credential() -> None:
    """One deliberate disclosure, in one place, and nowhere else.

    Every other subcommand's output is identifiers, states and times. If a
    listing or a status line ever printed a credential it would put one into a
    terminal, a shell history, and whatever file the output was redirected to —
    long after the operator had stopped expecting one.
    """
    printing = _print_calls_by_function()
    rendered = {
        name: " ".join(ast.unparse(call) for call in calls) for name, calls in printing.items()
    }
    assert "credential" in rendered["_register"]
    for name in ("_list", "_revoke"):
        assert "secret" not in rendered[name], f"{name} prints a secret"
    # `_status` prints the *shape* of the header an operator must send, which is
    # a documentation string with no value in it.
    assert "ClientCredential <client_id>:<secret>" in rendered["_status"]


def test_no_print_path_carries_the_digest() -> None:
    """The stored value never reaches a terminal, on any path.

    Not a credential, and still worth refusing: printing the digest beside the
    plaintext is how a reader comes to believe the digest is the thing to keep.
    """
    for name, calls in _print_calls_by_function().items():
        for call in calls:
            named = {node.id for node in ast.walk(call) if isinstance(node, ast.Name)} | {
                node.attr for node in ast.walk(call) if isinstance(node, ast.Attribute)
            }
            assert not named & SECRET_BEARING, f"{name} prints {sorted(named & SECRET_BEARING)}"


def test_the_status_line_names_the_address_the_transport_serves() -> None:
    """The restatement is a checked claim rather than a copy.

    The command may not import `my_pa.adapters` — an operator command that could
    reach a transport is on its way to being one — so it restates the ingress
    path. This is what keeps the restatement true.
    """
    assert command.INGRESS_PATH == REMOTE_CAPTURE_PATH


def test_minting_refuses_in_a_mode_that_authenticates_each_request() -> None:
    """A shell carries no bearer token, so there is no Principal to bind to.

    Refused rather than defaulted to the local operator, which is the same
    refusal `apps/gateway.py mcp` makes and for the same reason: binding a
    credential to the local operator in a mode configured to authenticate
    somebody else is the silent downgrade that mode exists to prevent.
    """
    entra = Settings(
        database_url=DSN,
        auth_mode=AuthMode.ENTRA,
        entra_tenant_id="synthetic-tenant",
        entra_client_id="synthetic-client",
        entra_issuer="https://example.invalid/synthetic/v2.0",
        entra_jwks_uri="https://example.invalid/synthetic/keys",
    )
    with pytest.raises(ValueError, match="no authenticated Principal"):
        command._bound_principal(entra)

    # The control: the mode that *does* have an answer gives one.
    assert command._bound_principal(Settings(database_url=DSN)).startswith("prn_")
