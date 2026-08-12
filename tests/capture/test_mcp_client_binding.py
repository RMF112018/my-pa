"""The MCP surface's kill switch and client binding, against a live registry.

WP-28 control 5. The switch and the binding are composed in
`bootstrap.gateway.mcp_surface_enabled` and reach the transport as one boolean;
`tests/security/test_mcp_surface_controls.py` proves what that boolean does to
`tools/list` and `tools/call`. This module proves what *sets* it, and it has to be
here rather than there because revocation is a row.

**The registry is WP-10's and is reused rather than reimplemented.**
`register_client` and `revoke_client` are the writers `apps/cli/clients.py` calls;
nothing new was built for this surface, and there is no second revocation
vocabulary to keep in step. A client that is absent, that belongs to another
Principal, or that has been revoked is **one answer**, on the registry's own rule
that "this credential used to work" is exactly what a refusal must not disclose.

**Binding is identification, not authentication.** stdio carries no credential
(`D-30`), so this process presents no secret and verifies none — what it does is
refuse to serve *as* a client an operator has withdrawn. Authenticating an
external MCP client requires an ingress that does not exist (`EXT-07`/`EXT-08`).
Nothing here should be read as per-client authentication.

Every value is synthetic and the database is the disposable one this directory's
fixture creates and drops.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Final

import pytest
from sqlalchemy import text

from my_pa.bootstrap.gateway import build_gateway_runtime, local_principal, mcp_surface_enabled
from my_pa.bootstrap.settings import Settings, SettingsError, load_settings
from my_pa.domain.capture.client import issue_client_secret
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.capture_clients import register_client, revoke_client
from my_pa.infrastructure.persistence.principal_scope import capture_context

pytestmark = pytest.mark.database

WHEN: Final = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)

#: A second Principal, so "a client this Principal does not hold" is a real row
#: rather than an absent one. Synthetic, and never the local operator's.
OTHER_PRINCIPAL: Final = "prn_bbbb0002bbbb0002bbbb0002"


@pytest.fixture
def engine(capture_database: str) -> Iterator[object]:
    """The disposable database with an empty client registry."""
    built = create_database_engine(capture_database)
    try:
        with built.begin() as connection:
            connection.execute(text("TRUNCATE knowledge.capture_clients CASCADE"))
        yield built
    finally:
        built.dispose()


def _register(engine: object, principal_id: str) -> str:
    _secret, digest = issue_client_secret()
    with engine.begin() as connection:  # type: ignore[attr-defined]
        client = register_client(
            connection,
            secret_sha256=digest,
            at=WHEN,
            context=capture_context(principal_id),
        )
    return client.client_id


def test_the_surface_serves_when_nothing_is_bound(capture_database: str, engine: object) -> None:
    """The default, and it is the state every process this build has ever run in.

    Empty means no client is bound. The surface is a pipe an operator started
    deliberately, so it serves; the switch exists to *withdraw* it, not to enable
    it.
    """
    settings = Settings(database_url=capture_database)
    assert settings.mcp_client_id == ""
    assert settings.mcp_surface_disabled is False
    assert mcp_surface_enabled(settings, engine, local_principal()) is True  # type: ignore[arg-type]


def test_the_kill_switch_wins_over_a_usable_client(capture_database: str, engine: object) -> None:
    """Engaged, the switch refuses regardless of how healthy the binding is.

    The client is registered and never revoked, so the only reason to refuse is
    the switch — which is what makes this a test of the switch rather than of the
    binding.
    """
    principal = local_principal()
    client_id = _register(engine, principal.principal_id)
    served = Settings(database_url=capture_database, mcp_client_id=client_id)
    assert mcp_surface_enabled(served, engine, principal) is True  # type: ignore[arg-type]

    killed = Settings(
        database_url=capture_database, mcp_client_id=client_id, mcp_surface_disabled=True
    )
    assert mcp_surface_enabled(killed, engine, principal) is False  # type: ignore[arg-type]


def test_a_revoked_client_is_refused(capture_database: str, engine: object) -> None:
    """Revocation through the existing operator path withdraws this surface.

    The same client, the same settings, before and after `revoke_client` — so the
    refusal is the revocation and nothing else. This is the whole of "reuse the
    existing registry": no second table, no second state vocabulary, and no second
    thing an operator has to remember to do.
    """
    principal = local_principal()
    client_id = _register(engine, principal.principal_id)
    settings = Settings(database_url=capture_database, mcp_client_id=client_id)
    assert mcp_surface_enabled(settings, engine, principal) is True  # type: ignore[arg-type]

    with engine.begin() as connection:  # type: ignore[attr-defined]
        revoke_client(
            connection,
            client_id,
            at=WHEN,
            context=capture_context(principal.principal_id),
        )
    assert mcp_surface_enabled(settings, engine, principal) is False  # type: ignore[arg-type]


def test_an_unknown_and_a_foreign_client_are_the_same_refusal(
    capture_database: str, engine: object
) -> None:
    """Absent, foreign and revoked are one answer, which is the registry's own rule.

    A foreign client is registered as a *real row* under another Principal, so
    this is a partition refusal rather than a lookup that found nothing.
    """
    principal = local_principal()
    foreign = _register(engine, OTHER_PRINCIPAL)
    unknown = "cli_00000000000000000000000000000000"

    for client_id in (foreign, unknown):
        settings = Settings(database_url=capture_database, mcp_client_id=client_id)
        assert mcp_surface_enabled(settings, engine, principal) is False, client_id  # type: ignore[arg-type]

    # The control: a client this Principal really holds is admitted by the same
    # call, so the two refusals above are about the binding rather than about a
    # lookup that never succeeds.
    mine = _register(engine, principal.principal_id)
    settings = Settings(database_url=capture_database, mcp_client_id=mine)
    assert mcp_surface_enabled(settings, engine, principal) is True  # type: ignore[arg-type]


def test_a_bound_client_with_no_process_principal_is_refused(
    capture_database: str, engine: object
) -> None:
    """`entra` mode has no process Principal, so there is no partition to look in.

    Refused rather than resolved against a guess: a binding that fell back to
    "any Principal's client" would make the surface's own withdrawal depend on
    whose row happened to match.
    """
    settings = Settings(database_url=capture_database, mcp_client_id="cli_0000000000000000000000")
    assert mcp_surface_enabled(settings, engine, None) is False  # type: ignore[arg-type]


def test_the_composition_carries_the_decision_to_the_runtime(capture_database: str) -> None:
    """`GatewayRuntime.mcp_enabled` is what `apps/gateway.py mcp` passes on.

    Composed once at startup rather than consulted per request, which is what
    makes the transport hold a boolean and no configuration.
    """
    served = build_gateway_runtime(Settings(database_url=capture_database))
    try:
        assert served.mcp_enabled is True
    finally:
        served.close()

    killed = build_gateway_runtime(
        Settings(database_url=capture_database, mcp_surface_disabled=True)
    )
    try:
        assert killed.mcp_enabled is False
    finally:
        killed.close()


def test_a_malformed_switch_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed on an unreadable value, in the direction that means "do not run".

    `MY_PA_MCP_SURFACE_DISABLED=maybe` is a process that does not start, rather
    than a switch silently read as `False` — which would be an operator believing
    they had withdrawn a surface that was still serving.
    """
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://my_pa@localhost:5433/my_pa")
    monkeypatch.setenv("MY_PA_MCP_SURFACE_DISABLED", "maybe")
    with pytest.raises(SettingsError):
        load_settings()

    # The control: the two spellings that *are* readable produce the two states,
    # so the refusal above is about the value rather than about the variable.
    for spelling, expected in (("true", True), ("false", False)):
        monkeypatch.setenv("MY_PA_MCP_SURFACE_DISABLED", spelling)
        assert load_settings().mcp_surface_disabled is expected
