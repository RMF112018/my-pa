"""Raw `grant` and Knowledge profile tooling bind Knowledge clients (KLP-WP-03, KLP-WP-04).

KLP-AC-146 (WP-03 slice). Raw `apps/cli/remote_mcp.py grant` refuses
`knowledge.assertions.create` -- a Knowledge write only profile tooling
(`profile-apply`) may install -- and any Knowledge grant whose Purpose is `None`.
The refusal is decided right after argument parsing, before settings are loaded
or a connection opened, so it exits non-zero and writes no row. The guard is
proved by patching the two seams `main` would reach next (settings and the
engine) to fail loudly: a refused command never reaches them.

The extraction plane's `knowledge.search`/`read`/`reveal`/`coverage` share the
`knowledge.` prefix and are unaffected (an explicit name set, KLP-AC-001).

KLP-WP-04 extends it (FAST; the remote-identity store is an in-memory SQLite copy
of `REMOTE_IDENTITY_METADATA`, as in `test_remote_mcp_chatllm_profile.py`):

* **KLP-AC-146 (whole).** Raw `grant` also refuses `knowledge.assertions.submit`
  and `knowledge.discovery.checkpoint`; `knowledge-profile-apply` is the only
  path that installs them.
* **KLP-AC-020.** For a client in the discovery or operator-review allowlist, raw
  `grant` refuses every capability outside that client's exact profile, before
  any connection, and prints the allowlist fingerprint it evaluated; profile
  commands print it too.
* **KLP-AC-040 (grant/profile half).** No grant or profile path plans or writes
  `review.decide` or `knowledge.assertions.create` for a discovery client: the
  ChatLLM profile tooling refuses a Knowledge-bound client outright, and
  `knowledge-profile-plan/apply` installs exactly the bound profile.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

import pytest
from apps.cli import remote_mcp
from apps.cli.remote_mcp import (
    KNOWLEDGE_GRANT_CAPABILITIES,
    KNOWLEDGE_WRITE_GRANT_CAPABILITIES,
    _run_knowledge_profile_command,
    _run_profile_command,
    knowledge_profile_refusal,
    main,
    raw_grant_refusal,
)
from sqlalchemy import create_engine

from my_pa.bootstrap.knowledge_discovery_profiles import (
    DISCOVERY_PROFILE,
    DISCOVERY_PROFILES,
    KNOWLEDGE_CLIENT_PROFILES,
    OPERATOR_REVIEW_PROFILE,
    KnowledgeAllowlists,
    allowlist_fingerprint,
    knowledge_allowlists,
)
from my_pa.bootstrap.settings import Settings, load_settings
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.chatllm_capability_policy import CHATLLM_DATA_PROFILE_VERSION
from my_pa.domain.identity.operation import Capability, is_write_capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.remote_identity import (
    REMOTE_IDENTITY_METADATA,
    RemoteIdentityRepository,
    remote_clients,
)

DISCOVERY_WRITES: Final = frozenset(
    {Capability.KNOWLEDGE_ASSERTIONS_SUBMIT, Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT}
)
KNOWLEDGE: Final = frozenset(
    {
        Capability.KNOWLEDGE_ASSERTIONS_READ,
        Capability.KNOWLEDGE_ASSERTIONS_LIST,
        Capability.KNOWLEDGE_ASSERTIONS_SEARCH,
        Capability.KNOWLEDGE_ASSERTIONS_HISTORY,
        Capability.KNOWLEDGE_ASSERTIONS_REVEAL,
        Capability.KNOWLEDGE_ASSERTIONS_CREATE,
    }
)


def _grant_argv(capability: Capability, purpose: Purpose | None) -> list[str]:
    argv = [
        "grant",
        "--oauth-client-id",
        "synthetic-client",
        "--scope",
        "my-pa.read",
        "--capability",
        capability.value,
        "--resource",
        "https://mcp.example.invalid/mcp",
    ]
    if purpose is not None:
        argv += ["--purpose", purpose.value]
    if capability is Capability.KNOWLEDGE_ASSERTIONS_CREATE or capability in DISCOVERY_WRITES:
        argv.append("--write")
    return argv


@pytest.fixture
def unreachable(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Settings and the engine fail loudly: a refusal must never reach either."""
    reached: list[str] = []

    def refuse(*_args: object, **_kwargs: object) -> object:
        reached.append("store")
        raise AssertionError("a refused raw grant reached the store")

    monkeypatch.setattr(remote_mcp, "load_settings", refuse)
    monkeypatch.setattr(remote_mcp, "create_database_engine", refuse)
    return reached


def test_the_governed_sets_are_exactly_the_knowledge_names() -> None:
    # KLP-WP-05: the `record_events.provenance` read joins the governed set.
    governed = KNOWLEDGE | DISCOVERY_WRITES | {Capability.RECORD_EVENTS_PROVENANCE}
    assert governed == KNOWLEDGE_GRANT_CAPABILITIES
    assert {
        Capability.KNOWLEDGE_ASSERTIONS_CREATE,
        *DISCOVERY_WRITES,
    } == KNOWLEDGE_WRITE_GRANT_CAPABILITIES
    assert (
        not {
            Capability.KNOWLEDGE_SEARCH,
            Capability.KNOWLEDGE_READ,
            Capability.KNOWLEDGE_REVEAL,
            Capability.KNOWLEDGE_COVERAGE,
        }
        & KNOWLEDGE_GRANT_CAPABILITIES
    )


@pytest.mark.parametrize("purpose", [None, Purpose.KNOWLEDGE_ASSERTION_AUTHORING])
def test_raw_grant_refuses_the_knowledge_write_and_writes_no_row(
    unreachable: list[str], capsys: pytest.CaptureFixture[str], purpose: Purpose | None
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(_grant_argv(Capability.KNOWLEDGE_ASSERTIONS_CREATE, purpose))
    assert raised.value.code != 0
    assert "profile-apply" in capsys.readouterr().err
    assert unreachable == []


@pytest.mark.parametrize(
    "capability", sorted(KNOWLEDGE - {Capability.KNOWLEDGE_ASSERTIONS_CREATE}), ids=str
)
def test_raw_grant_refuses_a_knowledge_read_without_a_purpose(
    unreachable: list[str], capsys: pytest.CaptureFixture[str], capability: Capability
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(_grant_argv(capability, None))
    assert raised.value.code != 0
    assert "without a purpose" in capsys.readouterr().err
    assert unreachable == []


@pytest.mark.parametrize(
    "capability", sorted(KNOWLEDGE - {Capability.KNOWLEDGE_ASSERTIONS_CREATE}), ids=str
)
def test_a_purposed_knowledge_read_passes_the_guard(capability: Capability) -> None:
    (purpose,) = permitted_purposes(capability)
    assert raw_grant_refusal(capability, purpose) is None


def test_non_knowledge_grants_are_unaffected() -> None:
    assert raw_grant_refusal(Capability.KNOWLEDGE_SEARCH, None) is None
    assert raw_grant_refusal(Capability.MEETINGS_CREATE, None) is None
    assert raw_grant_refusal(Capability.TASKS_READ, Purpose.TASK_READ) is None


# ---- KLP-WP-04 ----------------------------------------------------------------------


@pytest.mark.parametrize("capability", sorted(DISCOVERY_WRITES), ids=str)
@pytest.mark.parametrize("purpose", [None, Purpose.KNOWLEDGE_ASSERTION_OBSERVATION])
def test_raw_grant_refuses_the_discovery_writes_and_writes_no_row(
    unreachable: list[str],
    capsys: pytest.CaptureFixture[str],
    capability: Capability,
    purpose: Purpose | None,
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(_grant_argv(capability, purpose))
    assert raised.value.code != 0
    assert "knowledge-profile-apply" in capsys.readouterr().err
    assert unreachable == []


DISCOVERY_CLIENT: Final = "synthetic-discovery-client"
REVIEW_CLIENT: Final = "synthetic-operator-review-client"
CHAT_CLIENT: Final = "synthetic-chatllm-client"
UNBOUND_CLIENT: Final = "synthetic-unbound-client"
RESOURCE: Final = "https://mcp.example.invalid/mcp"
SCOPE: Final = "my-pa.read"
WHEN: Final = datetime(2026, 10, 5, 12, tzinfo=UTC)


def _bound_settings() -> Settings:
    return load_settings(
        {
            "MY_PA_DATABASE_URL": "postgresql+psycopg://someone@db.invalid:5432/somewhere",
            "MY_PA_KNOWLEDGE_DISCOVERY_OAUTH_CLIENT_IDS": DISCOVERY_CLIENT,
            "MY_PA_KNOWLEDGE_OPERATOR_REVIEW_OAUTH_CLIENT_IDS": REVIEW_CLIENT,
            "MY_PA_MCP_CHATLLM_GATEWAY_OAUTH_CLIENT_IDS": CHAT_CLIENT,
            "MY_PA_KNOWLEDGE_CHECKPOINT_SIGNING_KEY": "s" * 32,
        }
    )


@pytest.fixture
def bound(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Settings name the bound clients; the engine fails loudly if reached."""
    reached: list[str] = []
    settings = _bound_settings()

    def refuse(*_args: object, **_kwargs: object) -> object:
        reached.append("store")
        raise AssertionError("a refused raw grant reached the store")

    monkeypatch.setattr(remote_mcp, "load_settings", lambda: settings)
    monkeypatch.setattr(remote_mcp, "create_database_engine", refuse)
    return reached


def _client_argv(client: str, capability: Capability, purpose: Purpose | None) -> list[str]:
    argv = _grant_argv(capability, purpose)
    argv[argv.index("synthetic-client")] = client
    return argv


def _purpose(capability: Capability) -> Purpose:
    return sorted(permitted_purposes(capability), key=lambda member: member.value)[0]


@pytest.mark.parametrize(
    ("client", "capability"),
    [
        (DISCOVERY_CLIENT, Capability.TASKS_READ),
        (DISCOVERY_CLIENT, Capability.REVIEW_DECIDE),
        (DISCOVERY_CLIENT, Capability.REVIEW_LIST),
        (DISCOVERY_CLIENT, Capability.KNOWLEDGE_ASSERTIONS_LIST),
        (REVIEW_CLIENT, Capability.TASKS_READ),
        (REVIEW_CLIENT, Capability.RECORD_EVENTS_LIST),
        (REVIEW_CLIENT, Capability.KNOWLEDGE_ASSERTIONS_SEARCH),
    ],
    ids=lambda value: str(value),
)
def test_raw_grant_refuses_a_bound_client_anything_outside_its_profile(
    bound: list[str],
    capsys: pytest.CaptureFixture[str],
    client: str,
    capability: Capability,
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(_client_argv(client, capability, _purpose(capability)))
    assert raised.value.code != 0
    err = capsys.readouterr().err
    assert "outside that client's exact profile" in err
    assert (
        f"allowlist_fingerprint {allowlist_fingerprint(knowledge_allowlists(_bound_settings()))}"
        in err
    )
    assert bound == []


@pytest.mark.parametrize(
    ("client", "capability"),
    [
        (DISCOVERY_CLIENT, Capability.KNOWLEDGE_ASSERTIONS_READ),
        (DISCOVERY_CLIENT, Capability.RECORD_EVENTS_LIST),
        (REVIEW_CLIENT, Capability.REVIEW_LIST),
        (REVIEW_CLIENT, Capability.REVIEW_DECIDE),
        (REVIEW_CLIENT, Capability.KNOWLEDGE_ASSERTIONS_READ),
        (UNBOUND_CLIENT, Capability.TASKS_READ),
        (CHAT_CLIENT, Capability.TASKS_READ),
    ],
    ids=lambda value: str(value),
)
def test_in_profile_and_unbound_grants_pass_the_binding_guard(
    client: str, capability: Capability
) -> None:
    """The control: the guard refuses only what lies outside a bound profile."""
    allowlists = knowledge_allowlists(_bound_settings())
    assert (
        raw_grant_refusal(
            capability, _purpose(capability), allowlists=allowlists, oauth_client_id=client
        )
        is None
    )


def test_the_allowlist_fingerprint_is_sha256_of_the_canonical_sorted_allowlists() -> None:
    allowlists = KnowledgeAllowlists(
        discovery=frozenset({"d2", "d1"}),
        operator_review=frozenset({"r1"}),
        chatllm_gateway=frozenset(),
    )
    document = {
        "chatllm_gateway": [],
        "knowledge_discovery": ["d1", "d2"],
        "knowledge_operator_review": ["r1"],
    }
    expected = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert allowlist_fingerprint(allowlists) == expected
    moved = KnowledgeAllowlists(
        discovery=frozenset({"d1"}),
        operator_review=frozenset({"r1", "d2"}),
        chatllm_gateway=frozenset(),
    )
    assert allowlist_fingerprint(moved) != expected


@contextmanager
def _repository() -> Iterator[RemoteIdentityRepository]:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS identity")
        REMOTE_IDENTITY_METADATA.create_all(connection)
        for index, client in enumerate((DISCOVERY_CLIENT, REVIEW_CLIENT, UNBOUND_CLIENT)):
            connection.execute(
                remote_clients.insert().values(
                    id=UUID(int=index + 1),
                    principal_id=LOCAL_OPERATOR_UUID,
                    oauth_client_id=client,
                    client_name="synthetic Knowledge client",
                    redirect_uris='["https://client.example/callback"]',
                    registered_scopes=SCOPE,
                    enabled=True,
                    writes_enabled=True,
                    created_at=WHEN,
                )
            )
        yield RemoteIdentityRepository(connection)


def _knowledge_profile(
    repository: RemoteIdentityRepository,
    command: str,
    client: str,
    profile: str,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, object]:
    args = argparse.Namespace(
        command=command,
        oauth_client_id=client,
        scope=SCOPE,
        resource=RESOURCE,
        profile=profile,
        apply=command == "knowledge-profile-apply",
    )
    code = _run_knowledge_profile_command(
        argparse.ArgumentParser(prog="remote_mcp"), args, repository, _bound_settings(), WHEN
    )
    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["allowlist_fingerprint"] in captured.err
    return payload


def _rows(repository: RemoteIdentityRepository, client: str) -> set[tuple[str, str | None, bool]]:
    remote_client_id = repository.client_id_for_oauth_id(client)
    assert remote_client_id is not None
    return {
        (row.capability, row.purpose, bool(row.is_write))
        for row in repository.list_capability_grants(remote_client_id=remote_client_id)
    }


@pytest.mark.parametrize(
    ("client", "profile"),
    [(DISCOVERY_CLIENT, DISCOVERY_PROFILE), (REVIEW_CLIENT, OPERATOR_REVIEW_PROFILE)],
)
def test_knowledge_profile_apply_installs_exactly_the_bound_profile_and_converges(
    capsys: pytest.CaptureFixture[str], client: str, profile: str
) -> None:
    expected = {
        (capability.value, _purpose(capability).value, is_write_capability(capability))
        for capability in KNOWLEDGE_CLIENT_PROFILES[profile]
    }
    with _repository() as repository:
        plan = _knowledge_profile(repository, "knowledge-profile-plan", client, profile, capsys)
        assert plan["profile"] == profile
        assert {
            (action["capability"], action["purpose"], action["write"])  # type: ignore[index]
            for action in plan["actions"]  # type: ignore[attr-defined]
        } == expected
        assert _rows(repository, client) == set()
        _knowledge_profile(repository, "knowledge-profile-apply", client, profile, capsys)
        assert _rows(repository, client) == expected
        again = _knowledge_profile(repository, "knowledge-profile-plan", client, profile, capsys)
        assert again["actions"] == []


def test_the_discovery_profile_never_plans_create_or_review_decide(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _repository() as repository:
        _knowledge_profile(
            repository, "knowledge-profile-apply", DISCOVERY_CLIENT, DISCOVERY_PROFILE, capsys
        )
        granted = {capability for capability, _, _ in _rows(repository, DISCOVERY_CLIENT)}
    assert Capability.KNOWLEDGE_ASSERTIONS_CREATE.value not in granted
    assert Capability.REVIEW_DECIDE.value not in granted
    for name in DISCOVERY_PROFILES:
        for capability in (Capability.KNOWLEDGE_ASSERTIONS_CREATE, Capability.REVIEW_DECIDE):
            assert knowledge_profile_refusal(name, capability) is not None


def test_a_stray_grant_outside_the_profile_is_reported_and_never_extended(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _repository() as repository:
        remote_client_id = repository.client_id_for_oauth_id(DISCOVERY_CLIENT)
        assert remote_client_id is not None
        repository.grant(
            remote_client_id=remote_client_id,
            external_scope=SCOPE,
            capability=Capability.TASKS_READ,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            purpose=Purpose.TASK_READ,
        )
        plan = _knowledge_profile(
            repository, "knowledge-profile-plan", DISCOVERY_CLIENT, DISCOVERY_PROFILE, capsys
        )
    assert plan["outside_profile"] == [Capability.TASKS_READ.value]
    assert Capability.TASKS_READ.value not in {
        action["capability"]  # type: ignore[index]
        for action in plan["actions"]  # type: ignore[attr-defined]
    }


@pytest.mark.parametrize(
    ("client", "profile", "message"),
    [
        (UNBOUND_CLIENT, DISCOVERY_PROFILE, "not in a Knowledge"),
        (DISCOVERY_CLIENT, OPERATOR_REVIEW_PROFILE, "bound to knowledge-discovery-v2"),
        (REVIEW_CLIENT, DISCOVERY_PROFILE, "bound to knowledge-operator-review-v1"),
    ],
)
def test_knowledge_profile_commands_refuse_a_client_its_role_does_not_bind(
    capsys: pytest.CaptureFixture[str], client: str, profile: str, message: str
) -> None:
    with _repository() as repository:
        args = argparse.Namespace(
            command="knowledge-profile-apply",
            oauth_client_id=client,
            scope=SCOPE,
            resource=RESOURCE,
            profile=profile,
            apply=True,
        )
        with pytest.raises(SystemExit) as raised:
            _run_knowledge_profile_command(
                argparse.ArgumentParser(prog="remote_mcp"),
                args,
                repository,
                _bound_settings(),
                WHEN,
            )
        assert raised.value.code != 0
        assert message in capsys.readouterr().err
        assert _rows(repository, client) == set()


@pytest.mark.parametrize("command", ["profile-diff", "profile-plan", "profile-apply"])
@pytest.mark.parametrize("client", [DISCOVERY_CLIENT, REVIEW_CLIENT])
def test_the_chatllm_profile_tooling_refuses_a_knowledge_bound_client(
    capsys: pytest.CaptureFixture[str], command: str, client: str
) -> None:
    """KLP-AC-040: the ordinary profile names create and review.decide; never for them."""
    with _repository() as repository:
        args = argparse.Namespace(
            command=command,
            oauth_client_id=client,
            scope=SCOPE,
            resource=RESOURCE,
            profile_version=CHATLLM_DATA_PROFILE_VERSION,
            apply=True,
        )
        with pytest.raises(SystemExit) as raised:
            _run_profile_command(
                argparse.ArgumentParser(prog="remote_mcp"),
                args,
                repository,
                _bound_settings(),
                WHEN,
            )
        assert raised.value.code != 0
        err = capsys.readouterr().err
        assert "knowledge-profile-plan/apply" in err
        assert "allowlist_fingerprint " in err
        assert _rows(repository, client) == set()
