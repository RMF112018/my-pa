"""ChatLLM profile-apply renews expired grants without creating an expiry."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Final
from uuid import UUID

import pytest
from apps.cli.remote_mcp import _run_profile_command
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    chatllm_grant_purpose,
    composed_capabilities,
    desired_effective_capabilities,
)
from my_pa.application.service import _HANDLERS
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.chatllm_capability_policy import CHATLLM_DATA_PROFILE_VERSION
from my_pa.domain.identity.operation import Capability, is_write_capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.remote_identity import (
    REMOTE_IDENTITY_METADATA,
    RemoteIdentityRepository,
    remote_clients,
)

WHEN = datetime(2026, 9, 14, 12, tzinfo=UTC)
EXPIRED_AT = datetime(2026, 9, 13, 19, 48, 5, tzinfo=UTC)
CLIENT_ID = "synthetic-chatllm-client"
CLIENT_UUID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
RESOURCE = "https://my-pa.example/mcp"
SCOPE = "my-pa.read"


@contextmanager
def _repository() -> Iterator[tuple[Connection, RemoteIdentityRepository]]:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS identity")
        REMOTE_IDENTITY_METADATA.create_all(connection)
        connection.execute(
            remote_clients.insert().values(
                id=CLIENT_UUID,
                principal_id=LOCAL_OPERATOR_UUID,
                oauth_client_id=CLIENT_ID,
                client_name="synthetic ChatLLM",
                redirect_uris='["https://client.example/callback"]',
                registered_scopes=SCOPE,
                enabled=True,
                writes_enabled=True,
                created_at=WHEN,
            )
        )
        yield connection, RemoteIdentityRepository(connection)


def test_expired_grant_becomes_non_expiring_and_missing_grant_is_added() -> None:
    with _repository() as (_, repository):
        expired_id = repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.CONTEXT_PREPARE,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            expires_at=EXPIRED_AT,
            purpose=chatllm_grant_purpose(Capability.CONTEXT_PREPARE),
        )
        assert repository.clear_grant_expiry(grant_id=expired_id)
        added = repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.CAPTURE_CREATE,
            now=WHEN,
            is_write=is_write_capability(Capability.CAPTURE_CREATE),
            resource=RESOURCE,
            expires_at=None,
            purpose=chatllm_grant_purpose(Capability.CAPTURE_CREATE),
        )
        rows = {
            row.capability: row
            for row in repository.list_capability_grants(remote_client_id=CLIENT_UUID)
        }
        assert set(rows) == {Capability.CONTEXT_PREPARE.value, Capability.CAPTURE_CREATE.value}
        assert rows[Capability.CONTEXT_PREPARE.value].id == expired_id
        assert rows[Capability.CONTEXT_PREPARE.value].expires_at is None
        assert rows[Capability.CAPTURE_CREATE.value].id == added
        assert rows[Capability.CAPTURE_CREATE.value].expires_at is None
        assert repository.client_id_for_oauth_id(CLIENT_ID) == CLIENT_UUID


def test_clear_grant_expiry_on_active_finite_sets_null() -> None:
    """Clearing expiry on a finite-expiry active grant sets expires_at to NULL."""
    from datetime import timedelta

    future_expiry = WHEN + timedelta(days=30)
    with _repository() as (_, repository):
        finite_id = repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.TASKS_LIST,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            expires_at=future_expiry,
            purpose=chatllm_grant_purpose(Capability.TASKS_LIST),
        )
        rows_before = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_before) == 1
        assert rows_before[0].id == finite_id
        assert rows_before[0].expires_at is not None
        assert repository.clear_grant_expiry(grant_id=finite_id)
        rows_after = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_after) == 1
        assert rows_after[0].id == finite_id
        assert rows_after[0].expires_at is None


def test_profile_apply_idempotence_after_renew() -> None:
    """Applying renew action twice is idempotent; second clear succeeds without error."""
    from datetime import timedelta

    future_expiry = WHEN + timedelta(days=30)
    with _repository() as (_, repository):
        finite_id = repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.ENTITIES_SEARCH,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            expires_at=future_expiry,
            purpose=chatllm_grant_purpose(Capability.ENTITIES_SEARCH),
        )
        assert repository.clear_grant_expiry(grant_id=finite_id)
        rows_first = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_first) == 1
        assert rows_first[0].expires_at is None
        assert repository.clear_grant_expiry(grant_id=finite_id)
        rows_second = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_second) == 1
        assert rows_second[0].id == finite_id
        assert rows_second[0].expires_at is None


def test_transaction_rollback_on_apply_failure() -> None:
    """Transaction rollback reverts prior renew/add operations on failure."""
    from datetime import timedelta

    import pytest
    from sqlalchemy.exc import IntegrityError

    future_expiry = WHEN + timedelta(days=30)
    with _repository() as (connection, repository):
        finite_id = repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=Capability.TASKS_LIST,
            now=WHEN,
            is_write=False,
            resource=RESOURCE,
            expires_at=future_expiry,
            purpose=chatllm_grant_purpose(Capability.TASKS_LIST),
        )
        rows_before = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_before) == 1
        assert rows_before[0].expires_at is not None
        with pytest.raises((IntegrityError, Exception)), connection.begin_nested():
            assert repository.clear_grant_expiry(grant_id=finite_id)
            rows_mid = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
            assert rows_mid[0].expires_at is None
            raise IntegrityError("simulated failure", None, None)
        rows_after = list(repository.list_capability_grants(remote_client_id=CLIENT_UUID))
        assert len(rows_after) == 1
        assert rows_after[0].id == finite_id
        assert rows_after[0].expires_at is not None


#: Meeting Records WP-MTG-05: the six grants profile-apply must add, with the
#: single purpose each is stamped with.
_MEETING_PURPOSES = {
    Capability.MEETINGS_READ: Purpose.MEETING_READ,
    Capability.MEETINGS_LIST: Purpose.MEETING_READ,
    Capability.MEETINGS_SEARCH: Purpose.MEETING_READ,
    Capability.MEETINGS_CREATE: Purpose.MEETING_AUTHORING,
    Capability.MEETINGS_UPDATE: Purpose.MEETING_AUTHORING,
    Capability.MEETINGS_SERIES_UPDATE: Purpose.MEETING_AUTHORING,
}
_MEETING_WRITES = frozenset(
    {
        Capability.MEETINGS_CREATE,
        Capability.MEETINGS_UPDATE,
        Capability.MEETINGS_SERIES_UPDATE,
    }
)
#: A synthetic, fully composed deployment. Stands in for `Settings` so the
#: profile command never loads configuration or opens a database of its own.
_FULL_PLANE_SETTINGS = SimpleNamespace(
    managed_documents_are_composed=lambda: True,
    relationship_intelligence_enabled=True,
    relationship_intelligence_writes_enabled=True,
    relationship_memory_enabled=True,
    # KLP-WP-03: the Knowledge plane off, its default; the profile then
    # neither composes nor demands the six Knowledge grants.
    knowledge_assertions_enabled=False,
    # Record lineage P1 (chatllm-data-v10): both lineage switches off, their
    # defaults; the profile then neither composes nor demands a lineage grant.
    lineage_enabled=False,
    program_reporting_enabled=False,
    # CPM Workbench S5b-2 (chatllm-data-v11): the Schedule switch off, its default.
    schedule_enabled=False,
    # Schedule Scenarios S6-3 (chatllm-data-v13): the scenario switch off, its default.
    schedule_scenarios_enabled=False,
    # Files workspace WP5 (chatllm-data-v14): no workspace root, its default.
    files_workspace_is_composed=lambda: False,
    # KLP-WP-04: no client is Knowledge-bound, so the ChatLLM profile tooling runs.
    knowledge_discovery_oauth_client_id_set=frozenset,
    knowledge_operator_review_oauth_client_id_set=frozenset,
    chatllm_gateway_oauth_client_id_set=frozenset,
    knowledge_manager_oauth_client_id_set=frozenset,
)


def _profile(
    repository: RemoteIdentityRepository,
    command: str,
    capsys: pytest.CaptureFixture[str],
    *,
    profile_version: str = CHATLLM_DATA_PROFILE_VERSION,
) -> tuple[int, dict[str, object]]:
    """Run the operator profile command against the in-test store only."""
    args = argparse.Namespace(
        command=command,
        oauth_client_id=CLIENT_ID,
        scope=SCOPE,
        resource=RESOURCE,
        profile_version=profile_version,
        apply=command == "profile-apply",
    )
    code = _run_profile_command(
        argparse.ArgumentParser(prog="remote_mcp"),
        args,
        repository,
        _FULL_PLANE_SETTINGS,  # type: ignore[arg-type]
        WHEN,
    )
    return code, json.loads(capsys.readouterr().out)


def _grant_v2_catalog(repository: RemoteIdentityRepository) -> frozenset[Capability]:
    """Converge the client on everything the profile wants except the Meetings."""
    desired = desired_effective_capabilities(
        composed_capabilities(
            frozenset(_HANDLERS),
            ChatLLMCompositionPlanes(
                managed_documents=True,
                relationship_intelligence=True,
                relationship_intelligence_writes=True,
                relationship_memory=True,
                constraints=True,
            ),
        )
    )
    assert frozenset(_MEETING_PURPOSES) <= desired
    for capability in sorted(desired - frozenset(_MEETING_PURPOSES), key=lambda c: c.value):
        repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=capability,
            now=WHEN,
            is_write=is_write_capability(capability),
            resource=RESOURCE,
            expires_at=None,
            purpose=chatllm_grant_purpose(capability),
        )
    return desired


def test_profile_apply_adds_the_meeting_grants_once_and_then_converges(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _repository() as (_, repository):
        desired = _grant_v2_catalog(repository)
        code, plan = _profile(repository, "profile-plan", capsys)
        assert code == 1
        assert plan["profile_version"] == "chatllm-data-v14"
        assert plan["healthy"] is False
        assert plan["actions"] == [
            {
                "kind": "add",
                "capability": capability.value,
                "purpose": purpose.value,
                "write": capability in _MEETING_WRITES,
                "grant_id": None,
            }
            for capability, purpose in sorted(_MEETING_PURPOSES.items(), key=lambda i: i[0].value)
        ]

        code, applied = _profile(repository, "profile-apply", capsys)
        assert code == 0
        assert applied["applied"] is True
        rows = repository.list_capability_grants(remote_client_id=CLIENT_UUID)
        assert len(rows) == len(desired)
        meeting_rows = {
            row.capability: row for row in rows if row.capability.startswith("meetings.")
        }
        assert set(meeting_rows) == {capability.value for capability in _MEETING_PURPOSES}
        for capability, purpose in _MEETING_PURPOSES.items():
            row = meeting_rows[capability.value]
            assert row.purpose == purpose.value
            assert row.is_write is (capability in _MEETING_WRITES)
            assert row.capability_version == "v1"
            assert row.resource == RESOURCE
            assert row.external_scope == SCOPE
            assert row.expires_at is None
            assert row.revoked_at is None

        code, again = _profile(repository, "profile-apply", capsys)
        assert code == 0
        assert again["actions"] == []
        assert again["healthy"] is True
        assert len(repository.list_capability_grants(remote_client_id=CLIENT_UUID)) == len(desired)
        code, diff = _profile(repository, "profile-diff", capsys)
        assert code == 0
        assert diff["healthy"] is True
        assert diff["add"] == []
        assert diff["failing"] == []


def test_profile_commands_refuse_the_previous_profile_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _repository() as (_, repository):
        _grant_v2_catalog(repository)
        with pytest.raises(SystemExit) as raised:
            _profile(repository, "profile-apply", capsys, profile_version="chatllm-data-v9")
        assert raised.value.code == 2
        assert "profile version must be chatllm-data-v14" in capsys.readouterr().err
        rows = repository.list_capability_grants(remote_client_id=CLIENT_UUID)
        assert not any(row.capability.startswith("meetings.") for row in rows)


# ---- KLP-WP-03 (chatllm-data-v6, KLP-AC-106 WP-03 slice) --------------------------


def test_v6_profile_apply_adds_the_knowledge_grants_only_with_the_plane_on(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With the plane off the converged client is healthy; on, exactly seven adds.

    The node id is kept from KLP-WP-03 (KLP-AC-080): v6 added the six Knowledge
    names; v8 (KLP-WP-05) adds `record_events.provenance` on the same plane
    switch, so the plane-on plan now adds seven, each under its one purpose.
    """
    knowledge = {
        Capability.KNOWLEDGE_ASSERTIONS_READ: (Purpose.KNOWLEDGE_ASSERTION_READ, False),
        Capability.KNOWLEDGE_ASSERTIONS_LIST: (Purpose.KNOWLEDGE_ASSERTION_READ, False),
        Capability.KNOWLEDGE_ASSERTIONS_SEARCH: (Purpose.KNOWLEDGE_ASSERTION_READ, False),
        Capability.KNOWLEDGE_ASSERTIONS_HISTORY: (Purpose.KNOWLEDGE_ASSERTION_READ, False),
        Capability.KNOWLEDGE_ASSERTIONS_REVEAL: (Purpose.KNOWLEDGE_ASSERTION_READ, False),
        Capability.KNOWLEDGE_ASSERTIONS_CREATE: (Purpose.KNOWLEDGE_ASSERTION_AUTHORING, True),
        Capability.RECORD_EVENTS_PROVENANCE: (Purpose.RECORD_EVENT_PROVENANCE_READ, False),
    }
    with _repository() as (_, repository):
        _grant_v2_catalog(repository)
        _profile(repository, "profile-apply", capsys)
        code, off = _profile(repository, "profile-diff", capsys)
        assert code == 0 and off["healthy"] is True
        settings = SimpleNamespace(
            **{**vars(_FULL_PLANE_SETTINGS), "knowledge_assertions_enabled": True}
        )
        args = argparse.Namespace(
            command="profile-plan",
            oauth_client_id=CLIENT_ID,
            scope=SCOPE,
            resource=RESOURCE,
            profile_version=CHATLLM_DATA_PROFILE_VERSION,
            apply=False,
        )
        code = _run_profile_command(
            argparse.ArgumentParser(prog="remote_mcp"),
            args,
            repository,
            settings,  # type: ignore[arg-type]
            WHEN,
        )
        plan = json.loads(capsys.readouterr().out)
    assert code == 1
    assert plan["profile_version"] == "chatllm-data-v14"
    assert plan["actions"] == [
        {
            "kind": "add",
            "capability": capability.value,
            "purpose": purpose.value,
            "write": write,
            "grant_id": None,
        }
        for capability, (purpose, write) in sorted(knowledge.items(), key=lambda i: i[0].value)
    ]


# ---- Record lineage P1 (chatllm-data-v10, client exposure contract section 10) ----


def _lineage_exposed() -> tuple[frozenset[Capability], frozenset[Capability]]:
    """The 27 `LINEAGE` and 7 `PROGRAM_REPORTING` names, from the switch sets."""
    from my_pa.application.service import (
        _LINEAGE_CAPABILITIES,
        _PROGRAM_REPORTING_CAPABILITIES,
    )
    from my_pa.domain.lineage.vocabulary import (
        ATTESTED_LINEAGE_WRITE_CAPABILITIES,
        LINEAGE_BACKFILL_CAPABILITIES,
    )

    withheld = ATTESTED_LINEAGE_WRITE_CAPABILITIES | LINEAGE_BACKFILL_CAPABILITIES
    lineage = frozenset(c for c in _LINEAGE_CAPABILITIES if c.value not in withheld)
    return lineage, _PROGRAM_REPORTING_CAPABILITIES


def _plan_with(
    repository: RemoteIdentityRepository,
    settings: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, dict[str, object]]:
    args = argparse.Namespace(
        command="profile-plan",
        oauth_client_id=CLIENT_ID,
        scope=SCOPE,
        resource=RESOURCE,
        profile_version=CHATLLM_DATA_PROFILE_VERSION,
        apply=False,
    )
    code = _run_profile_command(
        argparse.ArgumentParser(prog="remote_mcp"),
        args,
        repository,
        settings,  # type: ignore[arg-type]
        WHEN,
    )
    return code, json.loads(capsys.readouterr().out)


def test_v10_profile_plan_adds_the_lineage_grants_only_with_the_switch_on(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Switch off: no lineage action; on: the 27 `LINEAGE` adds; with Program
    reporting and the entity plane: all 34, each under its one purpose."""
    from my_pa.domain.identity.operation import permitted_purposes

    lineage, program = _lineage_exposed()
    assert (len(lineage), len(program)) == (27, 7)
    every = {capability.value for capability in lineage | program}

    def adds(plan: dict[str, object]) -> dict[str, tuple[str, bool]]:
        actions = plan["actions"]
        assert isinstance(actions, list)
        return {
            action["capability"]: (action["purpose"], action["write"])
            for action in actions
            if action["kind"] == "add"
        }

    def expected(names: frozenset[Capability]) -> dict[str, tuple[str, bool]]:
        result: dict[str, tuple[str, bool]] = {}
        for capability in names:
            (purpose,) = permitted_purposes(capability)
            result[capability.value] = (purpose.value, is_write_capability(capability))
        return result

    with _repository() as (_, repository):
        _grant_v2_catalog(repository)
        _profile(repository, "profile-apply", capsys)
        # The switch off (the stand-in's default): converged, no lineage action.
        code, off = _plan_with(repository, _FULL_PLANE_SETTINGS, capsys)
        assert code == 0 and off["healthy"] is True
        assert off["profile_version"] == "chatllm-data-v14"
        assert not set(adds(off)) & every
        # The lineage switch on: exactly the 27 `LINEAGE` adds.
        on = SimpleNamespace(**{**vars(_FULL_PLANE_SETTINGS), "lineage_enabled": True})
        code, lineage_plan = _plan_with(repository, on, capsys)
        assert code == 1
        assert adds(lineage_plan) == expected(lineage)
        # Program reporting too, with the entity plane on: all 34.
        both = SimpleNamespace(
            **{
                **vars(_FULL_PLANE_SETTINGS),
                "lineage_enabled": True,
                "program_reporting_enabled": True,
            }
        )
        assert both.relationship_intelligence_enabled is True
        code, both_plan = _plan_with(repository, both, capsys)
        assert code == 1
        assert adds(both_plan) == expected(lineage | program)


# ---- KLP Step 8: the Knowledge Manager exact-client exception ----------------------

#: The Knowledge-Manager-exception pair: planned only for a bound manager.
_MANAGER_PAIR = frozenset(
    {Capability.KNOWLEDGE_ASSERTIONS_SUBMIT, Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT}
)


def _knowledge_settings(*, manager: bool) -> SimpleNamespace:
    """Every plane on, the Knowledge plane too; CLIENT_ID bound as manager or not."""
    return SimpleNamespace(
        **{
            **vars(_FULL_PLANE_SETTINGS),
            "knowledge_assertions_enabled": True,
            "chatllm_gateway_oauth_client_id_set": lambda: frozenset({CLIENT_ID}),
            "knowledge_manager_oauth_client_id_set": (
                (lambda: frozenset({CLIENT_ID})) if manager else frozenset
            ),
        }
    )


def _run(
    repository: RemoteIdentityRepository,
    command: str,
    settings: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, dict[str, object]]:
    args = argparse.Namespace(
        command=command,
        oauth_client_id=CLIENT_ID,
        scope=SCOPE,
        resource=RESOURCE,
        profile_version=CHATLLM_DATA_PROFILE_VERSION,
        apply=command == "profile-apply",
    )
    code = _run_profile_command(
        argparse.ArgumentParser(prog="remote_mcp"),
        args,
        repository,
        settings,  # type: ignore[arg-type]
        WHEN,
    )
    return code, json.loads(capsys.readouterr().out)


def _converge_ordinary(repository: RemoteIdentityRepository) -> frozenset[Capability]:
    """Grant every ordinary desired name with the Knowledge plane on."""
    desired = desired_effective_capabilities(
        composed_capabilities(
            frozenset(_HANDLERS),
            ChatLLMCompositionPlanes(
                managed_documents=True,
                relationship_intelligence=True,
                relationship_intelligence_writes=True,
                relationship_memory=True,
                constraints=True,
                knowledge_assertions=True,
            ),
        )
    )
    assert not _MANAGER_PAIR & desired
    for capability in sorted(desired, key=lambda c: c.value):
        repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=capability,
            now=WHEN,
            is_write=is_write_capability(capability),
            resource=RESOURCE,
            expires_at=None,
            purpose=chatllm_grant_purpose(capability),
        )
    return desired


def test_manager_profile_plan_adds_submit_and_checkpoint_then_converges(
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _knowledge_settings(manager=True)
    with _repository() as (_, repository):
        desired = _converge_ordinary(repository)
        code, plan = _run(repository, "profile-plan", settings, capsys)
        assert code == 1
        assert plan["knowledge_role"] == "manager"
        assert plan["unexpected_control_plane"] == []
        assert plan["actions"] == [
            {
                "kind": "add",
                "capability": capability.value,
                "purpose": Purpose.KNOWLEDGE_ASSERTION_OBSERVATION.value,
                "write": True,
                "grant_id": None,
            }
            for capability in sorted(_MANAGER_PAIR, key=lambda c: c.value)
        ]
        code, applied = _run(repository, "profile-apply", settings, capsys)
        assert code == 0 and applied["applied"] is True
        rows = {
            row.capability: row
            for row in repository.list_capability_grants(remote_client_id=CLIENT_UUID)
        }
        assert len(rows) == len(desired) + 2
        for capability in _MANAGER_PAIR:
            row = rows[capability.value]
            assert row.purpose == Purpose.KNOWLEDGE_ASSERTION_OBSERVATION.value
            assert row.is_write is True
            assert row.expires_at is None
        code, diff = _run(repository, "profile-diff", settings, capsys)
        assert code == 0
        assert diff["healthy"] is True
        assert diff["knowledge_role"] == "manager"
        assert diff["unexpected_control_plane"] == []
        for capability in _MANAGER_PAIR:
            assert diff["outcomes"][capability.value] == "IMPLEMENTED_COMPOSED_GRANTED"  # type: ignore[index]


def test_ordinary_profile_plan_never_adds_submit_or_checkpoint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _knowledge_settings(manager=False)
    with _repository() as (_, repository):
        _converge_ordinary(repository)
        code, plan = _run(repository, "profile-plan", settings, capsys)
        assert code == 0
        assert plan["knowledge_role"] == "ordinary"
        assert plan["actions"] == []
        for capability in sorted(_MANAGER_PAIR, key=lambda c: c.value):
            repository.grant(
                remote_client_id=CLIENT_UUID,
                external_scope=SCOPE,
                capability=capability,
                now=WHEN,
                is_write=True,
                resource=RESOURCE,
                expires_at=None,
                purpose=Purpose.KNOWLEDGE_ASSERTION_OBSERVATION,
            )
        code, diff = _run(repository, "profile-diff", settings, capsys)
        assert code == 1
        assert diff["healthy"] is False
        assert diff["unexpected_control_plane"] == sorted(c.value for c in _MANAGER_PAIR)
        assert not set(diff["desired_effective"]) & {c.value for c in _MANAGER_PAIR}  # type: ignore[arg-type]


# ---- Reports Modernization (chatllm-data-v12) ------------------------------------

#: The exact v11 -> v12 delta: the 11 Reports names, each with the purpose and
#: write flag the v12 planner stamps; `report_lifecycle` is its own purpose.
#: Ordered by capability value, as the planner orders its actions.
_V12_REPORTS_GRANTS = dict(
    sorted(
        {
            Capability.REPORTS_PUBLISH: (Purpose.REPORT_AUTHORING, True),
            Capability.REPORTS_UPDATE: (Purpose.REPORT_AUTHORING, True),
            Capability.REPORTS_HISTORY: (Purpose.REPORT_READ, False),
            Capability.REPORTS_ARCHIVE: (Purpose.REPORT_LIFECYCLE, True),
            Capability.REPORTS_DELETE: (Purpose.REPORT_LIFECYCLE, True),
            Capability.REPORTS_RESTORE: (Purpose.REPORT_LIFECYCLE, True),
            Capability.REPORTS_TRANSFER_BEGIN: (Purpose.REPORT_AUTHORING, True),
            Capability.REPORTS_TRANSFER_APPEND: (Purpose.REPORT_AUTHORING, True),
            Capability.REPORTS_TRANSFER_FINALIZE: (Purpose.REPORT_AUTHORING, True),
            Capability.REPORTS_TRANSFER_ABORT: (Purpose.REPORT_AUTHORING, True),
            Capability.REPORTS_TRANSFER_READ_CHUNK: (Purpose.REPORT_READ, False),
        }.items(),
        key=lambda item: item[0].value,
    )
)


def _grant_v11_catalog(repository: RemoteIdentityRepository) -> frozenset[Capability]:
    """Converge the client on everything v12 wants except the 11 Reports names (= v11)."""
    desired = desired_effective_capabilities(
        composed_capabilities(
            frozenset(_HANDLERS),
            ChatLLMCompositionPlanes(
                managed_documents=True,
                relationship_intelligence=True,
                relationship_intelligence_writes=True,
                relationship_memory=True,
                constraints=True,
            ),
        )
    )
    assert set(_V12_REPORTS_GRANTS) <= desired
    for capability in sorted(desired - set(_V12_REPORTS_GRANTS), key=lambda c: c.value):
        repository.grant(
            remote_client_id=CLIENT_UUID,
            external_scope=SCOPE,
            capability=capability,
            now=WHEN,
            is_write=is_write_capability(capability),
            resource=RESOURCE,
            expires_at=None,
            purpose=chatllm_grant_purpose(capability),
        )
    return desired


def test_v12_profile_diff_plan_and_apply_show_exactly_the_reports_delta(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A v11-converged client: diff, plan and apply move exactly the 11 Reports names.

    The operator-readable delta of the v11 -> v12 bump: `reports.publish`, the
    five management names and the five `reports.transfer.*` names, with
    `report_lifecycle` its own grant purpose. Synthetic in-memory store only; no
    real client or grant is touched.
    """
    names = [capability.value for capability in _V12_REPORTS_GRANTS]
    assert names == sorted(names)
    assert len(names) == 11
    with _repository() as (_, repository):
        desired = _grant_v11_catalog(repository)
        code, diff = _profile(repository, "profile-diff", capsys)
        assert code == 1
        assert diff["profile_version"] == "chatllm-data-v14"
        assert diff["healthy"] is False
        assert diff["add"] == names
        assert diff["renew"] == []
        assert diff["failing"] == names
        assert diff["unexpected_control_plane"] == []
        assert diff["policy_required_not_implemented"] == []
        for name in names:
            assert diff["outcomes"][name] == "IMPLEMENTED_COMPOSED_GRANT_MISSING"  # type: ignore[index]
        assert diff["desired_effective_count"] == len(desired)

        code, plan = _profile(repository, "profile-plan", capsys)
        assert code == 1
        assert plan["profile_version"] == "chatllm-data-v14"
        assert plan["actions"] == [
            {
                "kind": "add",
                "capability": capability.value,
                "purpose": purpose.value,
                "write": write,
                "grant_id": None,
            }
            for capability, (purpose, write) in _V12_REPORTS_GRANTS.items()
        ]
        assert len(repository.list_capability_grants(remote_client_id=CLIENT_UUID)) == (
            len(desired) - 11
        )

        code, applied = _profile(repository, "profile-apply", capsys)
        assert code == 0
        assert applied["actions"] == plan["actions"]
        rows = {
            row.capability: row
            for row in repository.list_capability_grants(remote_client_id=CLIENT_UUID)
            if row.capability in names
        }
        assert sorted(rows) == names
        for capability, (purpose, write) in _V12_REPORTS_GRANTS.items():
            row = rows[capability.value]
            assert (row.purpose, row.is_write, row.capability_version) == (
                purpose.value,
                write,
                "v1",
            )
            assert (row.resource, row.external_scope, row.expires_at, row.revoked_at) == (
                RESOURCE,
                SCOPE,
                None,
                None,
            )
        code, converged = _profile(repository, "profile-diff", capsys)
        assert code == 0
        assert converged["healthy"] is True
        for name in names:
            assert converged["outcomes"][name] == "IMPLEMENTED_COMPOSED_GRANTED"  # type: ignore[index]


#: The version after v14, which must not exist. Assembled, not spelled, so a
#: repository search for the literal finds nothing. (Reports was one bump,
#: v11 -> v12; Schedule Scenarios S6-3 one, v12 -> v13; the files workspace
#: WP5 one, v13 -> v14.)
_NONEXISTENT_NEXT_VERSION: Final = "chatllm-data-v" + str(15)


@pytest.mark.parametrize(
    "refused", ["chatllm-data-v12", "chatllm-data-v13", _NONEXISTENT_NEXT_VERSION]
)
def test_v14_profile_commands_refuse_earlier_versions_and_the_nonexistent_next_version(
    refused: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The v14 commands refuse the previous versions and the never-applied next one.

    Naming either changes nothing in the store.
    """
    with _repository() as (_, repository):
        _grant_v11_catalog(repository)
        with pytest.raises(SystemExit) as raised:
            _profile(repository, "profile-apply", capsys, profile_version=refused)
        assert raised.value.code == 2
        assert "profile version must be chatllm-data-v14" in capsys.readouterr().err
        rows = repository.list_capability_grants(remote_client_id=CLIENT_UUID)
        assert not {row.capability for row in rows} & {c.value for c in _V12_REPORTS_GRANTS}


# ---- Schedule Scenarios S6-3 (chatllm-data-v13) -----------------------------------


def test_v13_profile_plan_adds_the_22_scenario_grants_only_with_both_switches(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Schedule-scenarios contract sections 15.12.1 and 15.17 step 2.

    A client applied with the Schedule switch on stays healthy while the scenario
    switch is off (v13 then desires exactly the v12 set); with both switches on,
    the plan adds exactly the 22 client-usable names (the 6 writes under
    `schedule_analysis_authoring` with the write flag, the 16 reads under
    `schedule_analysis_read`) and never an operator baseline decision.
    Synthetic in-memory store only.
    """
    from my_pa.domain.identity.chatllm_capability_policy import SCHEDULE_SCENARIO_DATA_NAMES
    from my_pa.domain.identity.operation import is_operator_only, permitted_purposes

    schedule = SimpleNamespace(**{**vars(_FULL_PLANE_SETTINGS), "schedule_enabled": True})
    both = SimpleNamespace(**{**vars(schedule), "schedule_scenarios_enabled": True})
    scenario_only = SimpleNamespace(
        **{**vars(_FULL_PLANE_SETTINGS), "schedule_scenarios_enabled": True}
    )
    with _repository() as (_, repository):
        _grant_v2_catalog(repository)
        code, _ = _run(repository, "profile-apply", schedule, capsys)
        assert code == 0
        code, off = _run(repository, "profile-diff", schedule, capsys)
        assert code == 0 and off["healthy"] is True
        assert off["profile_version"] == "chatllm-data-v14"
        # The scenario switch without the Schedule switch composes nothing new.
        code, alone = _run(repository, "profile-plan", scenario_only, capsys)
        assert not {
            action["capability"]  # type: ignore[index]
            for action in alone["actions"]  # type: ignore[attr-defined]
            if action["kind"] == "add"  # type: ignore[index]
        } & {capability.value for capability in SCHEDULE_SCENARIO_DATA_NAMES}
        code, plan = _run(repository, "profile-plan", both, capsys)
        assert code == 1
        actions = plan["actions"]
        assert isinstance(actions, list)
        assert all(action["kind"] == "add" for action in actions)
        expected = {}
        for capability in SCHEDULE_SCENARIO_DATA_NAMES:
            assert not is_operator_only(capability)
            (purpose,) = permitted_purposes(capability)
            expected[capability.value] = (purpose.value, is_write_capability(capability))
        assert {
            action["capability"]: (action["purpose"], action["write"]) for action in actions
        } == expected
        assert len(expected) == 22
        assert sum(write for _, write in expected.values()) == 6


# ---- Files workspace WP5 (chatllm-data-v14) -----------------------------------------


def test_v14_profile_plan_adds_the_17_files_grants_only_with_the_workspace_root(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Files-workspace contract section 12: v14 with no root desires exactly the v13 set.

    A client converged without a workspace root stays healthy; with the root
    composed, the plan adds exactly the 17 `files.*` names (the 10 writes under
    `file_workspace_authoring` with the write flag, the 7 reads under
    `file_workspace_read`), none operator-only. Synthetic in-memory store only.
    """
    from my_pa.domain.identity.chatllm_capability_policy import FILES_WORKSPACE_DATA_NAMES
    from my_pa.domain.identity.operation import is_operator_only, permitted_purposes

    rooted = SimpleNamespace(
        **{**vars(_FULL_PLANE_SETTINGS), "files_workspace_is_composed": lambda: True}
    )
    with _repository() as (_, repository):
        _grant_v2_catalog(repository)
        code, _ = _run(repository, "profile-apply", _FULL_PLANE_SETTINGS, capsys)
        assert code == 0
        code, off = _run(repository, "profile-diff", _FULL_PLANE_SETTINGS, capsys)
        assert code == 0 and off["healthy"] is True
        assert off["profile_version"] == "chatllm-data-v14"
        code, plan = _run(repository, "profile-plan", rooted, capsys)
        assert code == 1
        actions = plan["actions"]
        assert isinstance(actions, list)
        assert all(action["kind"] == "add" for action in actions)
        expected = {}
        for capability in FILES_WORKSPACE_DATA_NAMES:
            assert not is_operator_only(capability)
            (purpose,) = permitted_purposes(capability)
            expected[capability.value] = (purpose.value, is_write_capability(capability))
        assert {
            action["capability"]: (action["purpose"], action["write"]) for action in actions
        } == expected
        assert len(expected) == 17
        assert sum(write for _, write in expected.values()) == 10
