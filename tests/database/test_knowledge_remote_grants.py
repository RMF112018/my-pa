"""KLP-WP-03: Knowledge grants on the real remote-identity store (KLP-AC-017, KLP-AC-146).

Marked `database` (auto `database_clone`), routed to `database-current-head`.

* **KLP-AC-017 (WP-03 slice).** With the global or the client write switch off,
  grant resolution drops the `knowledge.assertions.create` grant (`is_write`);
  with both on it survives; and a client with writes on but no create grant is
  denied create at the boundary while its read grants still resolve.
* **KLP-AC-146 (WP-03 slice).** Raw `grant` refuses `knowledge.assertions.create`
  and any Knowledge grant with Purpose `None`: it exits non-zero and the grant
  table gains no row. `profile-apply` -- the profile tooling -- is what installs
  the create grant, with its authoring purpose and `is_write`.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from apps.cli import remote_mcp
from apps.cli.remote_mcp import _run_profile_command, main
from sqlalchemy import Engine, func, select, update

from my_pa.adapters.remote_request import compose_remote_arguments
from my_pa.application.errors import UnsupportedError
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.remote_identity import (
    RemoteIdentityRepository,
    remote_capability_grants,
    remote_security_controls,
)

pytestmark = pytest.mark.database

WHEN = datetime(2026, 10, 4, 12, tzinfo=UTC)
SCOPE = "my-pa.read"
RESOURCE = "https://mcp.example.invalid/mcp"
CREATE = Capability.KNOWLEDGE_ASSERTIONS_CREATE
READS = (
    Capability.KNOWLEDGE_ASSERTIONS_READ,
    Capability.KNOWLEDGE_ASSERTIONS_LIST,
    Capability.KNOWLEDGE_ASSERTIONS_SEARCH,
    Capability.KNOWLEDGE_ASSERTIONS_HISTORY,
    Capability.KNOWLEDGE_ASSERTIONS_REVEAL,
)


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    composed = create_database_engine(disposable_database)
    try:
        yield composed
    finally:
        composed.dispose()


def _client(engine: Engine, oauth_client_id: str, *, client_writes: bool, create: bool) -> UUID:
    with engine.begin() as connection:
        repository = RemoteIdentityRepository(connection)
        client = repository.register_client(
            oauth_client_id=oauth_client_id,
            client_name="synthetic Knowledge client",
            redirect_uris='["https://client.example/callback"]',
            registered_scopes=SCOPE,
            now=WHEN,
            writes_enabled=client_writes,
        )
        for capability in READS:
            repository.grant(
                remote_client_id=client,
                external_scope=SCOPE,
                capability=capability,
                now=WHEN,
                is_write=False,
                resource=RESOURCE,
                purpose=Purpose.KNOWLEDGE_ASSERTION_READ,
            )
        if create:
            repository.grant(
                remote_client_id=client,
                external_scope=SCOPE,
                capability=CREATE,
                now=WHEN,
                is_write=True,
                resource=RESOURCE,
                purpose=Purpose.KNOWLEDGE_ASSERTION_AUTHORING,
            )
    return client


def _resolve(engine: Engine, oauth_client_id: str, *, global_writes: bool) -> object:
    with engine.begin() as connection:
        connection.execute(
            update(remote_security_controls).values(
                remote_enabled=True, writes_enabled=global_writes, updated_at=WHEN
            )
        )
        resolution = RemoteIdentityRepository(connection).authenticate(
            oauth_client_id=oauth_client_id,
            token_scopes=frozenset({SCOPE}),
            resource=RESOURCE,
            now=WHEN,
        )
    assert resolution is not None
    return resolution


@pytest.mark.parametrize(
    ("global_writes", "client_writes", "kept"),
    [(False, True, False), (True, False, False), (False, False, False), (True, True, True)],
    ids=["global-off", "client-off", "both-off", "both-on"],
)
def test_the_create_grant_is_dropped_at_resolution_unless_writes_are_on(
    engine: Engine, global_writes: bool, client_writes: bool, kept: bool
) -> None:
    oauth = f"klp03-{global_writes}-{client_writes}"
    _client(engine, oauth, client_writes=client_writes, create=True)
    resolution = _resolve(engine, oauth, global_writes=global_writes)
    assert set(READS) <= set(resolution.capabilities)  # type: ignore[attr-defined]
    assert (CREATE in resolution.capabilities) is kept  # type: ignore[attr-defined]
    purposes = resolution.capability_purposes  # type: ignore[attr-defined]
    assert ((CREATE, Purpose.KNOWLEDGE_ASSERTION_AUTHORING) in purposes) is kept


def test_writes_on_without_a_create_grant_is_denied_create(engine: Engine) -> None:
    oauth = "klp03-no-create"
    _client(engine, oauth, client_writes=True, create=False)
    resolution = _resolve(engine, oauth, global_writes=True)
    assert CREATE not in resolution.capabilities  # type: ignore[attr-defined]
    with pytest.raises(UnsupportedError):
        compose_remote_arguments(
            capability_name=CREATE.value,
            arguments={"payload": {}},
            principal=Principal(
                principal_id="prn_klp03remotegrant01",
                kind=PrincipalKind.OPERATOR,
                authenticated=True,
            ),
            grants=resolution.capability_purposes,  # type: ignore[attr-defined]
        )


def _grant_rows(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count()).select_from(remote_capability_grants)
            ).scalar_one()
        )


@pytest.mark.parametrize(
    ("capability", "purpose"),
    [
        (CREATE, Purpose.KNOWLEDGE_ASSERTION_AUTHORING),
        (CREATE, None),
        *((capability, None) for capability in READS),
    ],
    ids=lambda value: getattr(value, "value", str(value)),
)
def test_raw_grant_refuses_and_writes_no_row(
    engine: Engine,
    disposable_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capability: Capability,
    purpose: Purpose | None,
) -> None:
    _client(engine, "klp03-raw", client_writes=True, create=False)
    before = _grant_rows(engine)
    monkeypatch.setenv("MY_PA_DATABASE_URL", disposable_database)
    argv = [
        "grant",
        "--oauth-client-id",
        "klp03-raw",
        "--scope",
        SCOPE,
        "--capability",
        capability.value,
        "--resource",
        RESOURCE,
    ]
    if purpose is not None:
        argv += ["--purpose", purpose.value]
    if capability is CREATE:
        argv.append("--write")
    with pytest.raises(SystemExit) as raised:
        main(argv)
    assert raised.value.code != 0
    assert _grant_rows(engine) == before


def test_raw_grant_still_installs_a_purposed_knowledge_read(
    engine: Engine, disposable_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control: the guard refuses only what it names, and the path reaches the store."""
    _client(engine, "klp03-raw-ok", client_writes=False, create=False)
    with engine.begin() as connection:
        connection.execute(
            remote_capability_grants.delete().where(
                remote_capability_grants.c.capability == Capability.KNOWLEDGE_ASSERTIONS_READ.value
            )
        )
    before = _grant_rows(engine)
    monkeypatch.setenv("MY_PA_DATABASE_URL", disposable_database)
    (purpose,) = permitted_purposes(Capability.KNOWLEDGE_ASSERTIONS_READ)
    assert main(
        [
            "grant",
            "--oauth-client-id",
            "klp03-raw-ok",
            "--scope",
            SCOPE,
            "--capability",
            Capability.KNOWLEDGE_ASSERTIONS_READ.value,
            "--purpose",
            purpose.value,
            "--resource",
            RESOURCE,
        ]
    ) in (0, None)
    assert _grant_rows(engine) == before + 1


def test_profile_apply_installs_the_create_grant_with_its_purpose(
    engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _client(engine, "klp03-profile", client_writes=True, create=False)
    settings = SimpleNamespace(
        managed_documents_are_composed=lambda: True,
        relationship_intelligence_enabled=True,
        relationship_intelligence_writes_enabled=True,
        relationship_memory_enabled=True,
        knowledge_assertions_enabled=True,
    )
    args = argparse.Namespace(
        command="profile-apply",
        oauth_client_id="klp03-profile",
        scope=SCOPE,
        resource=RESOURCE,
        profile_version=remote_mcp.CHATLLM_DATA_PROFILE_VERSION,
        apply=True,
    )
    with engine.begin() as connection:
        code = _run_profile_command(
            argparse.ArgumentParser(prog="remote_mcp"),
            args,
            RemoteIdentityRepository(connection),
            settings,  # type: ignore[arg-type]
            WHEN,
        )
    assert code == 0, json.loads(capsys.readouterr().out)
    with engine.connect() as connection:
        row = connection.execute(
            select(remote_capability_grants).where(
                remote_capability_grants.c.remote_client_id == client,
                remote_capability_grants.c.capability == CREATE.value,
            )
        ).one()
    assert row.purpose == Purpose.KNOWLEDGE_ASSERTION_AUTHORING.value
    assert row.is_write is True
