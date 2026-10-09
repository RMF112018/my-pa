"""Knowledge grants on the real remote-identity store (KLP-WP-03, KLP-WP-04).

Marked `database` (auto `database_clone`), routed to `database-current-head`.

* **KLP-AC-017 (WP-03 slice).** With the global or the client write switch off,
  grant resolution drops the `knowledge.assertions.create` grant (`is_write`);
  with both on it survives; and a client with writes on but no create grant is
  denied create at the boundary while its read grants still resolve.
* **KLP-AC-146 (WP-03 slice).** Raw `grant` refuses `knowledge.assertions.create`
  and any Knowledge grant with Purpose `None`: it exits non-zero and the grant
  table gains no row. `profile-apply` -- the profile tooling -- is what installs
  the create grant, with its authoring purpose and `is_write`.

KLP-WP-04 slice A, on the same real store:

* **KLP-AC-017 (DB half).** The submit and checkpoint grants are `is_write` and
  dropped at grant resolution unless both write switches are on.
* **KLP-AC-019 / KLP-AC-134.** `apps.gateway.remote_access_context` over a real
  resolution intersects a discovery-bound client with its exact profile and an
  operator-review client with `knowledge-operator-review-v1`, for capabilities
  *and* purposes, even with conflicting grant rows; an unbound client loses
  submit and checkpoint; a stray `tasks.read` yields no task-family events.
* **KLP-AC-020 / KLP-AC-040.** A discovery or operator-review client is refused
  `knowledge.assertions.create` at the remote boundary although a create grant
  row exists; raw `grant` refuses a bound client anything outside its profile
  (exit non-zero, no row); `knowledge-profile-apply` installs exactly the bound
  profile and never `review.decide` or create; the ChatLLM profile tooling
  refuses a bound client and writes no row.
* **KLP-AC-146 (whole).** Raw `grant` refuses submit and checkpoint, no row.

The remote boundary's refusal of an ungranted capability is `unsupported`
(`compose_remote_arguments`), the vocabulary WP-03's create test already uses.
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
from apps.gateway import remote_access_context
from sqlalchemy import Engine, func, select, update

from my_pa.adapters.mcp.remote import RemoteAccessContext
from my_pa.adapters.remote_request import compose_remote_arguments
from my_pa.application.errors import UnsupportedError
from my_pa.application.record_events import visible_families
from my_pa.bootstrap.knowledge_discovery_profiles import (
    DISCOVERY_PROFILE,
    DISCOVERY_PROFILES,
    KNOWLEDGE_CLIENT_PROFILES,
    OPERATOR_REVIEW_PROFILE,
    allowlist_fingerprint,
    knowledge_allowlists,
)
from my_pa.bootstrap.settings import Settings, load_settings
from my_pa.domain.identity.operation import Capability, is_write_capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.record_events import RecordEventFamily
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.remote_identity import (
    RemoteIdentityRepository,
    remote_capability_grants,
    remote_security_controls,
)
from tests.conftest import FakeProviders, World, build_service

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
        knowledge_discovery_oauth_client_id_set=frozenset,
        knowledge_operator_review_oauth_client_id_set=frozenset,
        chatllm_gateway_oauth_client_id_set=frozenset,
        # KLP Step 8: the profile tooling reads the Knowledge Manager allowlist too.
        knowledge_manager_oauth_client_id_set=frozenset,
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


# ---- KLP-WP-04 ----------------------------------------------------------------------

DISCOVERY_CLIENT = "klp04-discovery"
REVIEW_CLIENT = "klp04-operator-review"
SUBMIT = Capability.KNOWLEDGE_ASSERTIONS_SUBMIT
CHECKPOINT = Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT
_ENVIRONMENT = {
    "MY_PA_KNOWLEDGE_DISCOVERY_OAUTH_CLIENT_IDS": DISCOVERY_CLIENT,
    "MY_PA_KNOWLEDGE_OPERATOR_REVIEW_OAUTH_CLIENT_IDS": REVIEW_CLIENT,
    "MY_PA_KNOWLEDGE_CHECKPOINT_SIGNING_KEY": "s" * 32,
}
#: A deliberately over-granted client: every name a bound profile could hold and
#: every conflicting name the overlay must strip.
_CONFLICTING = (
    (SUBMIT, Purpose.KNOWLEDGE_ASSERTION_OBSERVATION, True),
    (CHECKPOINT, Purpose.KNOWLEDGE_ASSERTION_OBSERVATION, True),
    (Capability.KNOWLEDGE_ASSERTIONS_READ, Purpose.KNOWLEDGE_ASSERTION_READ, False),
    (Capability.KNOWLEDGE_ASSERTIONS_LIST, Purpose.KNOWLEDGE_ASSERTION_READ, False),
    (CREATE, Purpose.KNOWLEDGE_ASSERTION_AUTHORING, True),
    (Capability.RECORD_EVENTS_LIST, Purpose.RECORD_EVENT_READ, False),
    # KLP-WP-05: the v2 discovery profile's provenance read.
    (Capability.RECORD_EVENTS_PROVENANCE, Purpose.RECORD_EVENT_PROVENANCE_READ, False),
    (Capability.REVIEW_LIST, Purpose.CAPTURE_REVIEW, False),
    (Capability.REVIEW_DECIDE, Purpose.REVIEW_DISPOSITION, True),
    (Capability.TASKS_READ, Purpose.TASK_READ, False),
)


def _settings(database_url: str) -> Settings:
    return load_settings({"MY_PA_DATABASE_URL": database_url, **_ENVIRONMENT})


def _granted_client(engine: Engine, oauth_client_id: str) -> UUID:
    with engine.begin() as connection:
        repository = RemoteIdentityRepository(connection)
        client = repository.register_client(
            oauth_client_id=oauth_client_id,
            client_name="synthetic Knowledge client",
            redirect_uris='["https://client.example/callback"]',
            registered_scopes=SCOPE,
            now=WHEN,
            writes_enabled=True,
        )
        for capability, purpose, is_write in _CONFLICTING:
            repository.grant(
                remote_client_id=client,
                external_scope=SCOPE,
                capability=capability,
                now=WHEN,
                is_write=is_write,
                resource=RESOURCE,
                purpose=purpose,
            )
    return client


def _context(engine: Engine, database_url: str, oauth_client_id: str) -> RemoteAccessContext:
    resolution = _resolve(engine, oauth_client_id, global_writes=True)
    authenticated = SimpleNamespace(
        principal=_PRINCIPAL,
        client_id=oauth_client_id,
        capabilities=resolution.capabilities,  # type: ignore[attr-defined]
        capability_purposes=resolution.capability_purposes,  # type: ignore[attr-defined]
        write_allowed=resolution.write_allowed,  # type: ignore[attr-defined]
    )
    service = build_service(World(), FakeProviders({}), knowledge_assertions_enabled=True)
    return remote_access_context(_settings(database_url), service, authenticated)  # type: ignore[arg-type]


_PRINCIPAL = Principal(
    principal_id="prn_klp04remotegrant1", kind=PrincipalKind.OPERATOR, authenticated=True
)


@pytest.mark.parametrize(
    ("global_writes", "client_writes", "kept"),
    [(False, True, False), (True, False, False), (True, True, True)],
    ids=["global-off", "client-off", "both-on"],
)
def test_the_discovery_write_grants_are_dropped_unless_writes_are_on(
    engine: Engine, global_writes: bool, client_writes: bool, kept: bool
) -> None:
    oauth = f"klp04-writes-{global_writes}-{client_writes}"
    with engine.begin() as connection:
        repository = RemoteIdentityRepository(connection)
        client = repository.register_client(
            oauth_client_id=oauth,
            client_name="synthetic discovery client",
            redirect_uris='["https://client.example/callback"]',
            registered_scopes=SCOPE,
            now=WHEN,
            writes_enabled=client_writes,
        )
        for capability in (SUBMIT, CHECKPOINT):
            repository.grant(
                remote_client_id=client,
                external_scope=SCOPE,
                capability=capability,
                now=WHEN,
                is_write=True,
                resource=RESOURCE,
                purpose=Purpose.KNOWLEDGE_ASSERTION_OBSERVATION,
            )
    resolution = _resolve(engine, oauth, global_writes=global_writes)
    for capability in (SUBMIT, CHECKPOINT):
        assert (capability in resolution.capabilities) is kept  # type: ignore[attr-defined]
        pair = (capability, Purpose.KNOWLEDGE_ASSERTION_OBSERVATION)
        assert (pair in resolution.capability_purposes) is kept  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("client", "expected"),
    [
        (DISCOVERY_CLIENT, DISCOVERY_PROFILES[DISCOVERY_PROFILE]),
        (REVIEW_CLIENT, KNOWLEDGE_CLIENT_PROFILES[OPERATOR_REVIEW_PROFILE]),
        ("klp04-unbound", frozenset(c for c, _, _ in _CONFLICTING) - {SUBMIT, CHECKPOINT}),
    ],
    ids=["discovery", "operator-review", "unbound"],
)
def test_gateway_resolution_overlays_capabilities_and_purposes(
    engine: Engine, disposable_database: str, client: str, expected: frozenset[Capability]
) -> None:
    _granted_client(engine, client)
    context = _context(engine, disposable_database, client)
    assert context.allowed_capabilities == {capability.value for capability in expected}
    assert context.capability_purposes is not None
    assert {capability for capability, _ in context.capability_purposes} == expected


def test_a_stray_tasks_grant_yields_no_task_events_for_a_discovery_client(
    engine: Engine, disposable_database: str
) -> None:
    _granted_client(engine, DISCOVERY_CLIENT)
    context = _context(engine, disposable_database, DISCOVERY_CLIENT)
    families = visible_families(frozenset(Capability), context.capability_purposes)
    assert RecordEventFamily.TASK not in families
    assert RecordEventFamily.KNOWLEDGE_ASSERTION in families


@pytest.mark.parametrize("client", [DISCOVERY_CLIENT, REVIEW_CLIENT])
def test_a_bound_client_is_denied_create_although_a_grant_row_exists(
    engine: Engine, disposable_database: str, client: str
) -> None:
    _granted_client(engine, client)
    resolution = _resolve(engine, client, global_writes=True)
    assert CREATE in resolution.capabilities  # type: ignore[attr-defined]
    context = _context(engine, disposable_database, client)
    assert CREATE.value not in (context.allowed_capabilities or frozenset())
    with pytest.raises(UnsupportedError):
        compose_remote_arguments(
            capability_name=CREATE.value,
            arguments={"payload": {}},
            principal=_PRINCIPAL,
            grants=context.capability_purposes,
        )


def test_a_discovery_client_never_receives_review_decide(
    engine: Engine, disposable_database: str
) -> None:
    _granted_client(engine, DISCOVERY_CLIENT)
    context = _context(engine, disposable_database, DISCOVERY_CLIENT)
    assert Capability.REVIEW_DECIDE.value not in (context.allowed_capabilities or frozenset())
    with pytest.raises(UnsupportedError):
        compose_remote_arguments(
            capability_name=Capability.REVIEW_DECIDE.value,
            arguments={"payload": {}},
            principal=_PRINCIPAL,
            grants=context.capability_purposes,
        )


def _environment(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", database_url)
    for name, value in _ENVIRONMENT.items():
        monkeypatch.setenv(name, value)


def _raw_grant(oauth: str, capability: Capability, purpose: Purpose, *, write: bool) -> list[str]:
    argv = [
        "grant",
        "--oauth-client-id",
        oauth,
        "--scope",
        SCOPE,
        "--capability",
        capability.value,
        "--purpose",
        purpose.value,
        "--resource",
        RESOURCE,
    ]
    return [*argv, "--write"] if write else argv


@pytest.mark.parametrize("capability", [SUBMIT, CHECKPOINT], ids=str)
def test_raw_grant_refuses_the_discovery_writes_and_writes_no_row(
    engine: Engine,
    disposable_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capability: Capability,
) -> None:
    _client(engine, DISCOVERY_CLIENT, client_writes=True, create=False)
    before = _grant_rows(engine)
    _environment(monkeypatch, disposable_database)
    with pytest.raises(SystemExit) as raised:
        main(
            _raw_grant(
                DISCOVERY_CLIENT, capability, Purpose.KNOWLEDGE_ASSERTION_OBSERVATION, write=True
            )
        )
    assert raised.value.code != 0
    assert _grant_rows(engine) == before


@pytest.mark.parametrize(
    ("oauth", "capability", "purpose"),
    [
        (DISCOVERY_CLIENT, Capability.TASKS_READ, Purpose.TASK_READ),
        (DISCOVERY_CLIENT, Capability.REVIEW_LIST, Purpose.CAPTURE_REVIEW),
        (REVIEW_CLIENT, Capability.RECORD_EVENTS_LIST, Purpose.RECORD_EVENT_READ),
    ],
)
def test_raw_grant_refuses_a_bound_client_anything_outside_its_profile(
    engine: Engine,
    disposable_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    oauth: str,
    capability: Capability,
    purpose: Purpose,
) -> None:
    _client(engine, oauth, client_writes=True, create=False)
    before = _grant_rows(engine)
    _environment(monkeypatch, disposable_database)
    with pytest.raises(SystemExit) as raised:
        main(_raw_grant(oauth, capability, purpose, write=False))
    assert raised.value.code != 0
    err = capsys.readouterr().err
    expected = allowlist_fingerprint(knowledge_allowlists(_settings(disposable_database)))
    assert f"allowlist_fingerprint {expected}" in err
    assert _grant_rows(engine) == before


def test_raw_grant_still_installs_an_in_profile_read_for_a_bound_client(
    engine: Engine, disposable_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control: the binding guard reaches the store for an in-profile grant."""
    _client(engine, DISCOVERY_CLIENT, client_writes=True, create=False)
    before = _grant_rows(engine)
    _environment(monkeypatch, disposable_database)
    assert main(
        _raw_grant(
            DISCOVERY_CLIENT,
            Capability.RECORD_EVENTS_LIST,
            Purpose.RECORD_EVENT_READ,
            write=False,
        )
    ) in (0, None)
    assert _grant_rows(engine) == before + 1


def _client_rows(engine: Engine, client: UUID) -> set[tuple[str, str | None, bool]]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(remote_capability_grants).where(
                remote_capability_grants.c.remote_client_id == client
            )
        ).all()
    return {(row.capability, row.purpose, bool(row.is_write)) for row in rows}


def _bare_client(engine: Engine, oauth: str) -> UUID:
    with engine.begin() as connection:
        return RemoteIdentityRepository(connection).register_client(
            oauth_client_id=oauth,
            client_name="synthetic Knowledge client",
            redirect_uris='["https://client.example/callback"]',
            registered_scopes=SCOPE,
            now=WHEN,
            writes_enabled=True,
        )


@pytest.mark.parametrize(
    ("oauth", "profile"),
    [(DISCOVERY_CLIENT, DISCOVERY_PROFILE), (REVIEW_CLIENT, OPERATOR_REVIEW_PROFILE)],
)
def test_knowledge_profile_apply_installs_exactly_the_bound_profile(
    engine: Engine,
    disposable_database: str,
    monkeypatch: pytest.MonkeyPatch,
    oauth: str,
    profile: str,
) -> None:
    client = _bare_client(engine, oauth)
    _environment(monkeypatch, disposable_database)
    argv = [
        "knowledge-profile-apply",
        "--oauth-client-id",
        oauth,
        "--scope",
        SCOPE,
        "--resource",
        RESOURCE,
        "--profile",
        profile,
        "--apply",
    ]
    assert main(argv) == 0
    installed = _client_rows(engine, client)
    assert installed == {
        (capability.value, purpose.value, is_write_capability(capability))
        for capability in KNOWLEDGE_CLIENT_PROFILES[profile]
        for purpose in permitted_purposes(capability)
    }
    if profile == DISCOVERY_PROFILE:
        names = {capability for capability, _, _ in installed}
        assert CREATE.value not in names
        assert Capability.REVIEW_DECIDE.value not in names
    assert main(argv) == 0
    assert _client_rows(engine, client) == installed, "apply converges"


@pytest.mark.parametrize("oauth", [DISCOVERY_CLIENT, REVIEW_CLIENT])
def test_the_chatllm_profile_apply_refuses_a_bound_client_and_writes_no_row(
    engine: Engine, disposable_database: str, monkeypatch: pytest.MonkeyPatch, oauth: str
) -> None:
    client = _bare_client(engine, oauth)
    _environment(monkeypatch, disposable_database)
    with pytest.raises(SystemExit) as raised:
        main(
            [
                "profile-apply",
                "--oauth-client-id",
                oauth,
                "--scope",
                SCOPE,
                "--resource",
                RESOURCE,
                "--profile-version",
                remote_mcp.CHATLLM_DATA_PROFILE_VERSION,
                "--apply",
            ]
        )
    assert raised.value.code != 0
    assert _client_rows(engine, client) == set()
