"""KLP-WP-03: raw `grant` refuses Knowledge write grants and purpose-less Knowledge grants.

KLP-AC-146 (WP-03 slice). Raw `apps/cli/remote_mcp.py grant` refuses
`knowledge.assertions.create` -- a Knowledge write only profile tooling
(`profile-apply`) may install -- and any Knowledge grant whose Purpose is `None`.
The refusal is decided right after argument parsing, before settings are loaded
or a connection opened, so it exits non-zero and writes no row. The guard is
proved by patching the two seams `main` would reach next (settings and the
engine) to fail loudly: a refused command never reaches them.

The extraction plane's `knowledge.search`/`read`/`reveal`/`coverage` share the
`knowledge.` prefix and are unaffected (an explicit name set, KLP-AC-001).
"""

from __future__ import annotations

from typing import Final

import pytest
from apps.cli import remote_mcp
from apps.cli.remote_mcp import (
    KNOWLEDGE_GRANT_CAPABILITIES,
    KNOWLEDGE_WRITE_GRANT_CAPABILITIES,
    main,
    raw_grant_refusal,
)

from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose

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
    if capability is Capability.KNOWLEDGE_ASSERTIONS_CREATE:
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
    assert KNOWLEDGE_GRANT_CAPABILITIES == KNOWLEDGE
    assert {Capability.KNOWLEDGE_ASSERTIONS_CREATE} == KNOWLEDGE_WRITE_GRANT_CAPABILITIES
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
