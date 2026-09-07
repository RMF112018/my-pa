"""Isolated PostgreSQL proofs for the bootstrap/recovery operator command.

The catalog is a disposable clone. WebAuthn settings are pointed at the
production RP and origin so the required assertions can match without aiming
the command at the canonical `my_pa` database.
"""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence
from contextlib import redirect_stderr, redirect_stdout

import apps.cli.auth as command
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.infrastructure.database.engine import create_database_engine

pytestmark = pytest.mark.database

HEAD = "4e9a1c7b2d60"
PRODUCTION_RP_ID = "pa.bobby-fetting.me"
PRODUCTION_ORIGIN = "https://pa.bobby-fetting.me"


@pytest.fixture(autouse=True)
def production_webauthn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_PA_WEBAUTHN_RP_ID", PRODUCTION_RP_ID)
    monkeypatch.setenv("MY_PA_WEBAUTHN_ALLOWED_ORIGINS", PRODUCTION_ORIGIN)


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    parsed = make_url(disposable_database)
    assert parsed.database is not None
    assert parsed.database != "my_pa"
    assert parsed.database.startswith("my_pa_p_")
    created = create_database_engine(disposable_database)
    try:
        yield created
    finally:
        created.dispose()


def _assertions(database_url: str, **overrides: str) -> list[str]:
    parsed = make_url(database_url)
    assert parsed.host is not None
    assert parsed.database is not None
    values = {
        "--expected-host": parsed.host,
        "--expected-port": str(parsed.port or 5432),
        "--expected-database": parsed.database,
        "--expected-alembic-head": HEAD,
        "--expected-rp-id": PRODUCTION_RP_ID,
        "--expected-origin": PRODUCTION_ORIGIN,
        "--expected-local-principal": str(LOCAL_OPERATOR_UUID),
    }
    values.update(overrides)
    argv: list[str] = []
    for option, value in values.items():
        argv.extend([option, value])
    return argv


def _invoke(argv: Sequence[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = command.main(list(argv))
    assert err.getvalue() == ""
    return status, out.getvalue()


def _grant_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(text("SELECT count(*) FROM identity.auth_grants")).scalar_one()
        )


def _field(printed: str, name: str) -> str | None:
    for line in printed.splitlines():
        head, _, rest = line.partition(" ")
        if head == name:
            return rest.strip()
    return None


def test_status_on_empty_uninitialized(disposable_database: str) -> None:
    status, out = _invoke(["bootstrap", "status", *_assertions(disposable_database)])
    assert status == command.EXIT_OK
    assert _field(out, "state") == "uninitialized"
    assert _field(out, "reason") == "bootstrap_required"
    assert _field(out, "grant") == "absent"
    assert _field(out, "expires") is None
    assert "grant_digest" not in out
    assert disposable_database not in out


def test_bootstrap_issue_once_then_refuses_and_status_omits_raw_grant(
    disposable_database: str,
) -> None:
    assertions = _assertions(disposable_database)
    first, issued = _invoke(
        ["bootstrap", "issue", *assertions, "--confirm-issue", "ISSUE_BOOTSTRAP_GRANT"]
    )
    raw = _field(issued, "grant")
    assert first == command.EXIT_OK
    assert raw is not None and len(raw) == 64
    assert _field(issued, "purpose") == "bootstrap"
    assert _field(issued, "expires") is not None
    assert "digest" not in issued.lower() or "SHA-256 digest" in issued

    second, refused = _invoke(
        ["bootstrap", "issue", *assertions, "--confirm-issue", "ISSUE_BOOTSTRAP_GRANT"]
    )
    assert second == command.EXIT_REFUSED
    assert refused.startswith("refused")
    assert raw not in refused

    status, observed = _invoke(["bootstrap", "status", *assertions])
    assert status == command.EXIT_OK
    assert _field(observed, "grant") == "active"
    assert _field(observed, "expires") is not None
    assert raw not in observed
    assert disposable_database not in observed


def test_revoke_then_status_absent(disposable_database: str) -> None:
    assertions = _assertions(disposable_database)
    issued_status, issued = _invoke(
        ["bootstrap", "issue", *assertions, "--confirm-issue", "ISSUE_BOOTSTRAP_GRANT"]
    )
    raw = _field(issued, "grant")
    assert issued_status == command.EXIT_OK
    revoked_status, revoked = _invoke(
        ["bootstrap", "revoke", *assertions, "--confirm-revoke", "REVOKE_BOOTSTRAP_GRANT"]
    )
    assert revoked_status == command.EXIT_OK
    assert _field(revoked, "state") == "revoked"
    assert raw not in revoked
    status, observed = _invoke(["bootstrap", "status", *assertions])
    assert status == command.EXIT_OK
    assert _field(observed, "grant") == "absent"
    assert raw not in observed


def test_recovery_issue_refused_while_uninitialized(disposable_database: str) -> None:
    status, out = _invoke(
        [
            "recovery",
            "issue",
            *_assertions(disposable_database),
            "--confirm-issue",
            "ISSUE_OPERATOR_RECOVERY_GRANT",
        ]
    )
    assert status == command.EXIT_REFUSED
    assert out.startswith("refused")
    assert "operator_recovery" in out


def test_mismatched_alembic_head_causes_zero_writes(
    disposable_database: str,
    engine: Engine,
) -> None:
    before = _grant_count(engine)
    status, out = _invoke(
        [
            "bootstrap",
            "issue",
            *_assertions(disposable_database, **{"--expected-alembic-head": "aaaaaaaaaaaa"}),
            "--confirm-issue",
            "ISSUE_BOOTSTRAP_GRANT",
        ]
    )
    assert status == command.EXIT_REFUSED
    assert out.startswith("refused")
    assert _grant_count(engine) == before
    assert disposable_database not in out
