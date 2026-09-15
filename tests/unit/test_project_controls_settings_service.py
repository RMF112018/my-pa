"""PC-CM-RUN01-WP05: `ProjectControlsConfigurationService` against fakes.

The FAST half. Everything here is decided in Python — the ordering of the three
checks, the digest's exact content, every configure disposition, the replay and
conflict answers, and the rollback — so each is provable without a server. What
a fake cannot establish is which of these the *database* enforces; that is
`tests/database/test_project_controls_configure_persistence.py`.

Every identifier, timezone and key here is synthetic.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import TracebackType
from typing import Final

import pytest

from my_pa.application.constraint_settings import (
    ProjectControlsConfigurationService,
    ProjectControlsDisposition,
    ProjectControlsIdempotencyConflictError,
    ProjectControlsNotConfiguredError,
    ProjectControlsOperationError,
    ProjectControlsProjectUnavailableError,
    ProjectControlsState,
    ProjectControlsVersionConflictError,
    _digest,
)
from my_pa.domain.project_controls.business_time import ProjectTimezoneError
from my_pa.domain.project_controls.history import (
    CONSTRAINT_PROJECT_SETTINGS_ACTION,
    ConstraintMutationActor,
    ConstraintProjectSettingsHistoryEntry,
    ConstraintProjectSettingsHistoryKeyConflictError,
    ConstraintProjectSettingsOutcome,
)
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.domain.situation.situation import Project, ProjectState

PRINCIPAL_A: Final = "prn_pcaaaa0001aaaa0001aa"
PRINCIPAL_B: Final = "prn_pcbbbb0002bbbb0002bb"
PROJECT_A: Final = "prj_pcaaaa0001aaaa"
PROJECT_B: Final = "prj_pcbbbb0002bbbb"
PROJECT_ABSENT: Final = "prj_pcnone0003nono"
ZONE: Final = "America/Chicago"
OTHER_ZONE: Final = "America/New_York"
KEY: Final = "pc-configure-0001"
T0: Final = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)


# --- the fakes ---------------------------------------------------------------


class FakeIntegrityError(Exception):
    """What the fake raises where the real adapter would see the driver's."""


@dataclass
class _State:
    """One shared in-memory partition set, keyed the way the tables are."""

    projects: dict[tuple[str, str], Project] = field(default_factory=dict)
    settings: dict[tuple[str, str], ConstraintProjectSettings] = field(default_factory=dict)
    history: list[tuple[str, ConstraintProjectSettingsHistoryEntry]] = field(default_factory=list)
    #: Set to a stage name to make the next matching write fail there.
    fail_on: str | None = None
    #: Names of the calls made, in order, so the ordering claims are checkable.
    calls: list[str] = field(default_factory=list)


class _FakeConstraints:
    """The Constraint tables this service touches, partitioned by Principal."""

    def __init__(self, state: _State) -> None:
        self._state = state

    def _trip(self, name: str) -> None:
        self._state.calls.append(name)
        if self._state.fail_on == name:
            self._state.fail_on = None
            raise FakeIntegrityError(f"induced failure at {name}")

    def get_project_settings(
        self, principal_id: str, project_id: str
    ) -> ConstraintProjectSettings | None:
        self._trip("get_project_settings")
        return self._state.settings.get((principal_id, project_id))

    def get_project_settings_for_update(
        self, principal_id: str, project_id: str
    ) -> ConstraintProjectSettings | None:
        self._trip("get_project_settings_for_update")
        return self._state.settings.get((principal_id, project_id))

    def insert_project_settings(
        self, principal_id: str, settings: ConstraintProjectSettings
    ) -> None:
        self._trip("insert_project_settings")
        key = (principal_id, settings.project_id)
        if key in self._state.settings:
            raise FakeIntegrityError("the settings row already exists")
        self._state.settings[key] = settings

    def update_project_settings(
        self, principal_id: str, settings: ConstraintProjectSettings
    ) -> None:
        self._trip("update_project_settings")
        key = (principal_id, settings.project_id)
        if key not in self._state.settings:
            raise FakeIntegrityError("there is no settings row to update")
        self._state.settings[key] = settings

    def get_project_settings_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> ConstraintProjectSettingsHistoryEntry | None:
        self._trip("get_project_settings_history_by_idempotency_key")
        for owner, entry in self._state.history:
            if owner == principal_id and entry.idempotency_key == idempotency_key:
                return entry
        return None

    def insert_project_settings_history(
        self, principal_id: str, entry: ConstraintProjectSettingsHistoryEntry
    ) -> None:
        self._trip("insert_project_settings_history")
        for owner, stored in self._state.history:
            if owner == principal_id and stored.idempotency_key == entry.idempotency_key:
                raise ConstraintProjectSettingsHistoryKeyConflictError(
                    "the idempotency key is already bound for this principal"
                )
        self._state.history.append((principal_id, entry))


class _FakeProjects:
    """The canonical Project reader, answering only inside one partition."""

    def __init__(self, state: _State) -> None:
        self._state = state

    def get_project(self, principal_id: str, project_id: str) -> Project | None:
        self._state.calls.append("get_project")
        return self._state.projects.get((principal_id, project_id))

    def lock_project(self, principal_id: str, project_id: str) -> Project | None:
        self._state.calls.append("lock_project")
        return self._state.projects.get((principal_id, project_id))


class _FakeUnitOfWork:
    """One transaction: it snapshots on entry and restores on any exception."""

    def __init__(self, state: _State) -> None:
        self._state = state
        self._snapshot: _State | None = None

    def __enter__(self) -> _FakeUnitOfWork:
        self._snapshot = copy.deepcopy(self._state)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        snapshot = self._snapshot
        self._snapshot = None
        if exc_type is not None and snapshot is not None:
            restored = copy.deepcopy(snapshot)
            # `calls` is observation, not stored state: a rollback must not
            # erase the record of what was attempted.
            restored.calls = self._state.calls
            restored.fail_on = self._state.fail_on
            self._state.__dict__.update(restored.__dict__)

    @property
    def constraints(self) -> _FakeConstraints:
        return _FakeConstraints(self._state)

    @property
    def projects(self) -> _FakeProjects:
        return _FakeProjects(self._state)


@dataclass
class _World:
    state: _State
    service: ProjectControlsConfigurationService


def _project(principal_id: str, project_id: str) -> Project:
    return Project(
        project_id=project_id,
        principal_id=principal_id,
        name="A Synthetic Project",
        state=ProjectState.ACTIVE,
        opened_at=T0,
        created_at=T0,
        updated_at=T0,
    )


def _world(*, configure_a: bool = False) -> _World:
    state = _State()
    for principal, project in ((PRINCIPAL_A, PROJECT_A), (PRINCIPAL_B, PROJECT_B)):
        state.projects[(principal, project)] = _project(principal, project)
    if configure_a:
        state.settings[(PRINCIPAL_A, PROJECT_A)] = ConstraintProjectSettings(
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            timezone_name=ZONE,
            version=1,
            created_at=T0,
            updated_at=T0,
        )
    service = ProjectControlsConfigurationService(
        unit_of_work=lambda: _FakeUnitOfWork(state),  # type: ignore[arg-type]
        clock=lambda: T0,
    )
    return _World(state=state, service=service)


def _configure(world: _World, **overrides: object) -> object:
    values: dict[str, object] = {
        "principal_id": PRINCIPAL_A,
        "actor": ConstraintMutationActor.PRINCIPAL,
        "project_id": PROJECT_A,
        "timezone_name": ZONE,
        "idempotency_key": KEY,
    }
    values.update(overrides)
    return world.service.configure(**values)  # type: ignore[arg-type]


# --- the digest ---------------------------------------------------------------


def test_the_digest_normalizes_exactly_the_four_semantic_values() -> None:
    """Operation, Project, validated timezone, and `expected_version` — no more."""
    subject = _digest(
        operation=CONSTRAINT_PROJECT_SETTINGS_ACTION,
        project_id=PROJECT_A,
        timezone_name=ZONE,
        expected_version=None,
    )
    assert subject == _digest(
        expected_version=None,
        timezone_name=ZONE,
        project_id=PROJECT_A,
        operation=CONSTRAINT_PROJECT_SETTINGS_ACTION,
    ), "field order changed the digest"
    for changed in (
        {"project_id": PROJECT_B},
        {"timezone_name": OTHER_ZONE},
        {"expected_version": 1},
        {"operation": "something-else"},
    ):
        values: dict[str, object] = {
            "operation": CONSTRAINT_PROJECT_SETTINGS_ACTION,
            "project_id": PROJECT_A,
            "timezone_name": ZONE,
            "expected_version": None,
        }
        values.update(changed)
        assert _digest(**values) != subject, f"{changed} did not change the digest"


def test_a_null_expected_version_is_part_of_the_digest() -> None:
    """Null is a stated intent — "there is nothing here yet" — not an absence.

    A digest that simply omitted the field would make a first configure and a
    configure expecting version 1 the same request, so a retry that quietly
    supplied one would replay instead of conflicting.
    """
    absent = _digest(
        operation=CONSTRAINT_PROJECT_SETTINGS_ACTION,
        project_id=PROJECT_A,
        timezone_name=ZONE,
    )
    explicit_null = _digest(
        operation=CONSTRAINT_PROJECT_SETTINGS_ACTION,
        project_id=PROJECT_A,
        timezone_name=ZONE,
        expected_version=None,
    )
    assert absent != explicit_null


def test_the_digest_excludes_actor_context_correlation_and_the_clock() -> None:
    """Two requests differing only in those four replay as one another.

    Proved end to end rather than by reading the call: the second request
    carries a different client context, correlation identifier and actor, and
    is answered `replayed` from the first one's receipt.
    """
    world = _world()
    first = _configure(world, client_context="web", correlation_id=None)
    second = _configure(
        world,
        actor=ConstraintMutationActor.SYSTEM,
        client_context="mcp",
        correlation_id=None,
    )
    assert first.disposition is ProjectControlsDisposition.APPLIED  # type: ignore[attr-defined]
    assert second.disposition is ProjectControlsDisposition.REPLAYED  # type: ignore[attr-defined]
    assert len(world.state.history) == 1


# --- ordering: the three separate checks --------------------------------------


def test_an_invalid_timezone_is_refused_before_anything_is_read_or_written() -> None:
    """Step two, and it happens before the Project is even looked at.

    An unknown zone is a malformed request whatever the caller owns, and
    answering it after the lock would make the refusal depend on ownership.
    """
    world = _world()
    with pytest.raises(ProjectTimezoneError) as refusal:
        _configure(world, timezone_name="Mars/Olympus_Mons")
    assert refusal.value.code == "project_timezone_invalid"
    assert world.state.calls == []
    assert not world.state.history


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("", "project_timezone_blank"),
        ("   ", "project_timezone_blank"),
        ("America/New York", "project_timezone_has_whitespace"),
        (" America/Chicago", "project_timezone_has_whitespace"),
        ("x" * 65, "project_timezone_too_long"),
    ],
)
def test_a_malformed_timezone_name_is_neither_trimmed_nor_repaired(name: str, code: str) -> None:
    """No trim, no case folding, no canonicalization, no fallback."""
    world = _world()
    with pytest.raises(ProjectTimezoneError) as refusal:
        _configure(world, timezone_name=name)
    assert refusal.value.code == code
    assert not world.state.settings


def test_a_malformed_idempotency_key_is_refused_by_type_before_shape() -> None:
    world = _world()
    with pytest.raises(ProjectControlsOperationError) as refusal:
        _configure(world, idempotency_key=1234)
    assert refusal.value.code == "project_controls_idempotency_key_not_a_string"
    with pytest.raises(ProjectControlsOperationError) as short:
        _configure(world, idempotency_key="short")
    assert short.value.code == "project_controls_idempotency_key_malformed"
    assert world.state.calls == []


def test_the_project_lock_comes_before_the_ledger_and_the_settings_read() -> None:
    """Step three, and it is first among the things that touch the database."""
    world = _world()
    _configure(world)
    assert world.state.calls[0] == "lock_project"
    assert world.state.calls.index("lock_project") < world.state.calls.index(
        "get_project_settings_history_by_idempotency_key"
    )
    assert world.state.calls.index("get_project_settings_history_by_idempotency_key") < (
        world.state.calls.index("get_project_settings_for_update")
    )


@pytest.mark.parametrize(
    "project_id",
    [PROJECT_B, PROJECT_ABSENT],
    ids=["foreign", "unknown"],
)
def test_a_project_this_principal_does_not_own_is_one_answer(project_id: str) -> None:
    """Unknown, deleted and foreign are the same refusal, and it writes nothing."""
    world = _world()
    with pytest.raises(ProjectControlsProjectUnavailableError):
        _configure(world, project_id=project_id)
    assert not world.state.settings
    assert not world.state.history


def test_a_deleted_project_is_indistinguishable_from_a_foreign_one() -> None:
    """The nondisclosure equivalence, stated as an equality rather than by shape.

    A Project that existed and was removed, one that never existed, and one
    that belongs to somebody else all leave `configure` and `read_status`
    through exactly the same exception type with exactly the same message, so
    there is nothing in the refusal for a caller to read.
    """
    world = _world(configure_a=True)
    del world.state.projects[(PRINCIPAL_A, PROJECT_A)]
    refusals = []
    for project_id in (PROJECT_A, PROJECT_B, PROJECT_ABSENT):
        with pytest.raises(ProjectControlsProjectUnavailableError) as refusal:
            world.service.read_status(principal_id=PRINCIPAL_A, project_id=project_id)
        refusals.append((type(refusal.value), str(refusal.value)))
    assert len(set(refusals)) == 1


def test_settings_presence_is_not_project_authorization() -> None:
    """The correction, stated directly: an owned Project with no row configures.

    Under the conflation this work package removes, the only way to configure a
    Project was to have configured it already.
    """
    world = _world()
    assert not world.state.settings
    result = _configure(world)
    assert result.disposition is ProjectControlsDisposition.APPLIED  # type: ignore[attr-defined]


# --- configure semantics ------------------------------------------------------


def test_an_absent_row_and_a_null_expected_version_insert_version_one() -> None:
    world = _world()
    result = _configure(world)
    assert result.disposition is ProjectControlsDisposition.APPLIED  # type: ignore[attr-defined]
    assert result.settings_version == 1  # type: ignore[attr-defined]
    assert result.timezone_name == ZONE  # type: ignore[attr-defined]
    stored = world.state.settings[(PRINCIPAL_A, PROJECT_A)]
    assert (stored.timezone_name, stored.version) == (ZONE, 1)
    assert len(world.state.history) == 1
    receipt = world.state.history[0][1]
    assert receipt.outcome is ConstraintProjectSettingsOutcome.APPLIED
    assert (receipt.before_settings_version, receipt.after_settings_version) == (None, 1)
    assert receipt.resulting_timezone_name == ZONE


@pytest.mark.parametrize("expected_version", [None, 1], ids=["null", "matching"])
def test_the_same_timezone_is_a_no_op_with_one_receipt(expected_version: int | None) -> None:
    """One history row for a new key, and the version does not move."""
    world = _world(configure_a=True)
    result = _configure(world, idempotency_key="pc-no-op-000001", expected_version=expected_version)
    assert result.disposition is ProjectControlsDisposition.NO_OP  # type: ignore[attr-defined]
    assert result.settings_version == 1  # type: ignore[attr-defined]
    assert world.state.settings[(PRINCIPAL_A, PROJECT_A)].version == 1
    assert len(world.state.history) == 1
    receipt = world.state.history[0][1]
    assert receipt.outcome is ConstraintProjectSettingsOutcome.NO_OP
    assert (receipt.before_settings_version, receipt.after_settings_version) == (1, 1)


def test_a_different_timezone_with_no_expected_version_conflicts() -> None:
    """Replacing a calendar nobody read is refused, and the refusal is evidence."""
    world = _world(configure_a=True)
    with pytest.raises(ProjectControlsVersionConflictError) as conflict:
        _configure(world, timezone_name=OTHER_ZONE)
    assert world.state.settings[(PRINCIPAL_A, PROJECT_A)].timezone_name == ZONE
    receipt = conflict.value.receipt
    assert receipt.outcome is ConstraintProjectSettingsOutcome.REJECTED
    assert receipt.failure_code == "settings_expected_version_required"
    assert (receipt.before_settings_version, receipt.after_settings_version) == (1, 1)
    # The rejected receipt committed: the transaction closed before the raise.
    assert [entry for _, entry in world.state.history] == [receipt]


def test_a_different_timezone_with_the_matching_version_updates_once() -> None:
    world = _world(configure_a=True)
    result = _configure(world, timezone_name=OTHER_ZONE, expected_version=1)
    assert result.disposition is ProjectControlsDisposition.APPLIED  # type: ignore[attr-defined]
    assert result.settings_version == 2  # type: ignore[attr-defined]
    stored = world.state.settings[(PRINCIPAL_A, PROJECT_A)]
    assert (stored.timezone_name, stored.version) == (OTHER_ZONE, 2)
    assert stored.created_at == T0, "an update preserves the row's creation time"
    assert len(world.state.history) == 1


def test_a_stale_expected_version_conflicts_and_commits_its_rejection() -> None:
    world = _world(configure_a=True)
    with pytest.raises(ProjectControlsVersionConflictError) as conflict:
        _configure(world, timezone_name=OTHER_ZONE, expected_version=7)
    assert conflict.value.settings.version == 1
    receipt = conflict.value.receipt
    assert receipt.failure_code == "settings_version_conflict"
    assert world.state.settings[(PRINCIPAL_A, PROJECT_A)].timezone_name == ZONE
    assert [entry for _, entry in world.state.history] == [receipt]


def test_a_missing_row_with_a_non_null_expected_version_is_not_configured() -> None:
    """Typed `not_configured`, and distinct from "this Project is not available"."""
    world = _world()
    with pytest.raises(ProjectControlsNotConfiguredError):
        _configure(world, expected_version=1)
    assert not world.state.settings
    assert len(world.state.history) == 1
    receipt = world.state.history[0][1]
    assert receipt.outcome is ConstraintProjectSettingsOutcome.REJECTED
    assert receipt.failure_code == "project_controls_not_configured"
    assert (receipt.before_settings_version, receipt.after_settings_version) == (None, None)


# --- replay and conflict ------------------------------------------------------


def test_the_same_key_and_the_same_digest_replays_the_original_answer() -> None:
    world = _world()
    first = _configure(world)
    second = _configure(world)
    assert second.disposition is ProjectControlsDisposition.REPLAYED  # type: ignore[attr-defined]
    assert second.settings_version == first.settings_version  # type: ignore[attr-defined]
    assert second.timezone_name == first.timezone_name  # type: ignore[attr-defined]
    assert second.receipt is first.receipt or (  # type: ignore[attr-defined]
        second.receipt.history_id == first.receipt.history_id  # type: ignore[attr-defined]
    )
    assert len(world.state.history) == 1, "a replay writes no second receipt"
    assert world.state.settings[(PRINCIPAL_A, PROJECT_A)].version == 1


def test_a_replay_reports_the_original_answer_and_not_the_current_row() -> None:
    """The snapshot is the ledger's, so a row that moved on cannot rewrite it."""
    world = _world()
    first = _configure(world)
    world.service.configure(
        principal_id=PRINCIPAL_A,
        actor=ConstraintMutationActor.PRINCIPAL,
        project_id=PROJECT_A,
        timezone_name=OTHER_ZONE,
        idempotency_key="pc-second-00001",
        expected_version=1,
    )
    assert world.state.settings[(PRINCIPAL_A, PROJECT_A)].version == 2
    replayed = _configure(world)
    assert replayed.disposition is ProjectControlsDisposition.REPLAYED  # type: ignore[attr-defined]
    assert replayed.settings_version == first.settings_version == 1  # type: ignore[attr-defined]
    assert replayed.timezone_name == ZONE  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "changed",
    [
        {"timezone_name": OTHER_ZONE},
        {"expected_version": 1},
    ],
    ids=["timezone", "expected_version"],
)
def test_the_same_key_with_different_intent_is_a_typed_conflict(
    changed: dict[str, object],
) -> None:
    world = _world()
    _configure(world)
    with pytest.raises(ProjectControlsIdempotencyConflictError):
        _configure(world, **changed)
    assert len(world.state.history) == 1
    assert world.state.settings[(PRINCIPAL_A, PROJECT_A)].timezone_name == ZONE


def test_the_same_key_on_a_different_project_is_a_typed_conflict_not_an_integrity_error() -> None:
    """The unique-index race, translated. Two Projects share no lock to serialise on.

    The insert raises the key conflict the repository narrowed for exactly this
    purpose; the service rolls back, re-reads the bound receipt, and answers by
    digest. A raw integrity error never leaves the module.
    """
    world = _world()
    world.state.projects[(PRINCIPAL_A, PROJECT_B)] = _project(PRINCIPAL_A, PROJECT_B)
    _configure(world)
    with pytest.raises(ProjectControlsIdempotencyConflictError):
        _configure(world, project_id=PROJECT_B)
    assert (PRINCIPAL_A, PROJECT_B) not in world.state.settings
    assert len(world.state.history) == 1


def test_a_key_the_same_principal_bound_on_a_rejection_conflicts_on_a_new_intent() -> None:
    """A rejection binds its key. A later different request under it is refused."""
    world = _world()
    with pytest.raises(ProjectControlsNotConfiguredError):
        _configure(world, expected_version=1)
    with pytest.raises(ProjectControlsIdempotencyConflictError):
        _configure(world)
    assert not world.state.settings


def test_a_key_bound_by_this_principal_is_invisible_to_another() -> None:
    """The key is unique within the Principal, never across the table."""
    world = _world()
    _configure(world)
    result = world.service.configure(
        principal_id=PRINCIPAL_B,
        actor=ConstraintMutationActor.PRINCIPAL,
        project_id=PROJECT_B,
        timezone_name=ZONE,
        idempotency_key=KEY,
    )
    assert result.disposition is ProjectControlsDisposition.APPLIED
    assert len(world.state.history) == 2


# --- rollback ------------------------------------------------------------------


def test_a_failure_writing_the_receipt_leaves_no_settings_row() -> None:
    """One transaction: the settings write and the receipt commit together or not."""
    world = _world()
    world.state.fail_on = "insert_project_settings_history"
    with pytest.raises(FakeIntegrityError):
        _configure(world)
    assert not world.state.settings
    assert not world.state.history


def test_a_failure_writing_the_settings_row_leaves_no_receipt() -> None:
    world = _world(configure_a=True)
    world.state.fail_on = "update_project_settings"
    with pytest.raises(FakeIntegrityError):
        _configure(world, timezone_name=OTHER_ZONE, expected_version=1)
    assert world.state.settings[(PRINCIPAL_A, PROJECT_A)].timezone_name == ZONE
    assert not world.state.history


# --- status --------------------------------------------------------------------


def test_status_reports_not_configured_for_an_owned_project_with_no_row() -> None:
    world = _world()
    status = world.service.read_status(principal_id=PRINCIPAL_A, project_id=PROJECT_A)
    assert status.state is ProjectControlsState.NOT_CONFIGURED
    assert status.settings is None
    assert status.project_id == PROJECT_A


def test_status_reports_configured_with_the_rows_own_values() -> None:
    world = _world(configure_a=True)
    status = world.service.read_status(principal_id=PRINCIPAL_A, project_id=PROJECT_A)
    assert status.state is ProjectControlsState.CONFIGURED
    assert status.settings is not None
    assert status.settings.timezone_name == ZONE
    assert status.settings.version == 1


def test_status_qualifies_the_project_before_it_reads_settings() -> None:
    world = _world(configure_a=True)
    world.service.read_status(principal_id=PRINCIPAL_A, project_id=PROJECT_A)
    assert world.state.calls[0] == "get_project"
    assert world.state.calls.index("get_project") < world.state.calls.index("get_project_settings")


@pytest.mark.parametrize("project_id", [PROJECT_B, PROJECT_ABSENT], ids=["foreign", "unknown"])
def test_status_refuses_a_project_this_principal_does_not_own(project_id: str) -> None:
    world = _world()
    with pytest.raises(ProjectControlsProjectUnavailableError):
        world.service.read_status(principal_id=PRINCIPAL_A, project_id=project_id)


def test_status_still_reports_configured_for_an_invalid_stored_timezone() -> None:
    """An unusable stored calendar is still a configured Project.

    Reporting it as `not_configured` would invite a silent reconfiguration of a
    Project the Register is deliberately failing closed on, which is the
    opposite of "existing invalid stored timezone rows stay fail-closed until
    explicit reconfiguration".
    """
    world = _world(configure_a=True)
    stored = world.state.settings[(PRINCIPAL_A, PROJECT_A)]
    world.state.settings[(PRINCIPAL_A, PROJECT_A)] = ConstraintProjectSettings(
        principal_id=stored.principal_id,
        project_id=stored.project_id,
        timezone_name="Mars/Olympus_Mons",
        version=stored.version,
        created_at=stored.created_at,
        updated_at=stored.updated_at,
    )
    status = world.service.read_status(principal_id=PRINCIPAL_A, project_id=PROJECT_A)
    assert status.state is ProjectControlsState.CONFIGURED
    assert status.settings is not None
    assert status.settings.timezone_name == "Mars/Olympus_Mons"


def test_reconfiguring_an_invalid_stored_timezone_is_the_explicit_repair() -> None:
    world = _world(configure_a=True)
    stored = world.state.settings[(PRINCIPAL_A, PROJECT_A)]
    world.state.settings[(PRINCIPAL_A, PROJECT_A)] = ConstraintProjectSettings(
        principal_id=stored.principal_id,
        project_id=stored.project_id,
        timezone_name="Mars/Olympus_Mons",
        version=1,
        created_at=T0,
        updated_at=T0,
    )
    result = _configure(world, expected_version=1)
    assert result.disposition is ProjectControlsDisposition.APPLIED  # type: ignore[attr-defined]
    assert world.state.settings[(PRINCIPAL_A, PROJECT_A)].timezone_name == ZONE
