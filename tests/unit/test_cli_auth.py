"""The auth operator command as a parser and as a fail-closed output surface.

No database. What is checked here is the shape an operator meets and the
properties that keep a mistyped target from opening a connection:

* there is no `--principal-id`, `--database-url`, or `--dsn` option;
* issue and revoke require an exact confirmation token, not a boolean flag;
* a pre-connect mismatch never creates an engine;
* refusals never echo a DSN-shaped string;
* status keys are non-secret.
"""

from __future__ import annotations

import argparse
import io
import re
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock

import apps.cli.auth as command
import pytest
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError

from my_pa.bootstrap.settings import Settings
from my_pa.domain.identity.auth_state import AuthStateKind, AuthStateReason
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID

DSN = "postgresql+psycopg://operator@db.invalid:5432/somewhere"
HEAD = "c1a8e4d70b29"
DSN_SHAPED = re.compile(r"[a-z0-9+]+://\S+", re.IGNORECASE)
STATUS_KEYS = frozenset({"state", "reason", "grant", "expires"})
SECRET_KEYS = frozenset(
    {
        "digest",
        "grant_digest",
        "raw_grant",
        "dsn",
        "database_url",
        "connection_string",
        "password",
    }
)


def _options(parser: argparse.ArgumentParser) -> set[str]:
    return {
        option
        for action in parser._actions
        for option in action.option_strings
        if option not in {"-h", "--help"}
    }


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": DSN,
        "webauthn_rp_id": command.PRODUCTION_RP_ID,
        "webauthn_allowed_origins": command.PRODUCTION_ORIGIN,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _load_settings() -> Settings:
    return _settings()


def _assertions(**overrides: str) -> list[str]:
    values = {
        "--expected-host": "db.invalid",
        "--expected-port": "5432",
        "--expected-database": "somewhere",
        "--expected-alembic-head": HEAD,
        "--expected-rp-id": command.PRODUCTION_RP_ID,
        "--expected-origin": command.PRODUCTION_ORIGIN,
        "--expected-local-principal": str(LOCAL_OPERATOR_UUID),
    }
    values.update(overrides)
    argv: list[str] = []
    for option, value in values.items():
        argv.extend([option, value])
    return argv


def _invoke(argv: Sequence[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = command.main(list(argv))
    return status, out.getvalue(), err.getvalue()


def _output_keys(printed: str) -> set[str]:
    return {line.split()[0] for line in printed.splitlines() if line.split()}


def _record_engine(created: list[object]) -> Callable[..., MagicMock]:
    def factory(url: URL, statement_timeout_ms: int | None = None) -> MagicMock:
        created.append((url, statement_timeout_ms))
        return MagicMock()

    return factory


def test_parser_has_no_principal_or_dsn_options() -> None:
    options = _options(command.build_parser())
    assert "--principal-id" not in options
    assert "--database-url" not in options
    assert "--dsn" not in options
    assert "--confirm-issue" in options
    assert "--confirm-revoke" in options


def test_confirmation_is_not_a_boolean_flag() -> None:
    parser = command.build_parser()
    issue = next(action for action in parser._actions if "--confirm-issue" in action.option_strings)
    revoke = next(
        action for action in parser._actions if "--confirm-revoke" in action.option_strings
    )
    assert not isinstance(issue, argparse._StoreTrueAction)
    assert not isinstance(revoke, argparse._StoreTrueAction)
    assert issue.nargs != 0
    assert revoke.nargs != 0
    with pytest.raises(SystemExit):
        parser.parse_args(["bootstrap", "issue", *_assertions(), "--confirm-issue"])


@pytest.mark.parametrize(
    ("plane", "action", "flag", "token"),
    [
        ("bootstrap", "issue", "--confirm-issue", "ISSUE_OPERATOR_RECOVERY_GRANT"),
        ("recovery", "issue", "--confirm-issue", "ISSUE_BOOTSTRAP_GRANT"),
        ("bootstrap", "revoke", "--confirm-revoke", "REVOKE_OPERATOR_RECOVERY_GRANT"),
        ("recovery", "revoke", "--confirm-revoke", "REVOKE_BOOTSTRAP_GRANT"),
        ("bootstrap", "issue", "--confirm-issue", "true"),
        ("bootstrap", "revoke", "--confirm-revoke", "yes"),
    ],
)
def test_wrong_confirmation_refuses_without_opening_an_engine(
    monkeypatch: pytest.MonkeyPatch,
    plane: str,
    action: str,
    flag: str,
    token: str,
) -> None:
    created: list[object] = []
    monkeypatch.setattr(command, "load_settings", _load_settings)
    monkeypatch.setattr(command, "create_database_engine", _record_engine(created))
    status, out, _err = _invoke([plane, action, *_assertions(), flag, token])
    assert status == command.EXIT_REFUSED
    assert out.startswith("refused")
    assert created == []
    assert DSN not in out
    assert DSN_SHAPED.search(out) is None


def test_missing_confirmation_refuses_without_opening_an_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[object] = []
    monkeypatch.setattr(command, "load_settings", _load_settings)
    monkeypatch.setattr(command, "create_database_engine", _record_engine(created))
    status, out, _err = _invoke(["bootstrap", "issue", *_assertions()])
    assert status == command.EXIT_REFUSED
    assert "confirmation" in out
    assert created == []
    assert DSN_SHAPED.search(out) is None


@pytest.mark.parametrize(
    "override",
    [
        {"--expected-host": "other.invalid"},
        {"--expected-port": "65535"},
        {"--expected-database": "elsewhere"},
        {"--expected-rp-id": "localhost"},
        {"--expected-origin": "https://localhost"},
        {"--expected-local-principal": "00000000-0000-0000-0000-000000000000"},
    ],
)
def test_pre_connect_mismatch_never_opens_an_engine(
    monkeypatch: pytest.MonkeyPatch,
    override: dict[str, str],
) -> None:
    created: list[object] = []
    monkeypatch.setattr(command, "load_settings", _load_settings)
    monkeypatch.setattr(command, "create_database_engine", _record_engine(created))
    status, out, _err = _invoke(["bootstrap", "status", *_assertions(**override)])
    assert status == command.EXIT_REFUSED
    assert out.startswith("refused")
    assert created == []
    assert DSN not in out
    assert DSN_SHAPED.search(out) is None


def test_settings_relying_party_mismatch_never_opens_an_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[object] = []
    monkeypatch.setattr(
        command,
        "load_settings",
        lambda: _settings(webauthn_rp_id="localhost", webauthn_allowed_origins="http://localhost"),
    )
    monkeypatch.setattr(command, "create_database_engine", _record_engine(created))
    status, out, _err = _invoke(["bootstrap", "status", *_assertions()])
    assert status == command.EXIT_REFUSED
    assert created == []
    assert DSN_SHAPED.search(out) is None


def test_driver_error_does_not_echo_a_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = MagicMock()
    engine.begin.side_effect = OperationalError(
        f"could not connect to {DSN}",
        {"dsn": DSN},
        Exception(DSN),
    )

    def factory(url: URL, statement_timeout_ms: int | None = None) -> MagicMock:
        _ = url, statement_timeout_ms
        return engine

    monkeypatch.setattr(command, "load_settings", _load_settings)
    monkeypatch.setattr(command, "create_database_engine", factory)
    status, out, _err = _invoke(["bootstrap", "status", *_assertions()])
    assert status == command.EXIT_REFUSED
    assert "unreachable" in out
    assert DSN not in out
    assert DSN_SHAPED.search(out) is None
    engine.dispose.assert_called_once()


def test_status_output_keys_are_non_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value = MagicMock()

    def factory(url: URL, statement_timeout_ms: int | None = None) -> MagicMock:
        _ = url, statement_timeout_ms
        return engine

    def skip_identity(connection: object, args: argparse.Namespace) -> None:
        _ = connection, args

    def validator(connection: object) -> SimpleNamespace:
        _ = connection
        state = SimpleNamespace(
            kind=AuthStateKind.UNINITIALIZED,
            reasons=(AuthStateReason.BOOTSTRAP_REQUIRED,),
        )
        return SimpleNamespace(inspect=lambda now: state)

    def store(connection: object) -> SimpleNamespace:
        _ = connection
        return SimpleNamespace(active=lambda purpose, *, now: None)

    monkeypatch.setattr(command, "load_settings", _load_settings)
    monkeypatch.setattr(command, "create_database_engine", factory)
    monkeypatch.setattr(command, "_assert_connected_identity", skip_identity)
    monkeypatch.setattr(command, "AuthStateValidator", validator)
    monkeypatch.setattr(command, "AuthGrantStore", store)
    status, out, _err = _invoke(["bootstrap", "status", *_assertions()])
    assert status == command.EXIT_OK
    keys = _output_keys(out)
    assert keys <= STATUS_KEYS
    assert not keys & SECRET_KEYS
    assert DSN not in out
    assert DSN_SHAPED.search(out) is None
