"""WP-12B native-source values are opaque, immutable, exact, and fail closed."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from my_pa.domain.native_sources import (
    ContactMembership,
    ExactBucketSelection,
    LiveActivationGate,
    LiveActivationGateState,
    NativeBridge,
    NativeCheckpoint,
    NativeConfigurationRevision,
    NativeSourceAccount,
    NativeSourceBucket,
    NativeSourceKind,
    SimulationReceipt,
    WatcherSimulation,
    WatcherSimulationState,
)
from my_pa.domain.source.provider import (
    ObjectKind,
    SourceObject,
    SourceObjectContent,
    SourceProvider,
)
from my_pa.domain.source.registry import SourceProviderKind

WHEN = datetime(2026, 8, 4, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


def _id(prefix: str, ordinal: int) -> str:
    return f"{prefix}_{ordinal:016d}"


def _selection() -> ExactBucketSelection:
    return ExactBucketSelection((_id("nbkt", 2), _id("nbkt", 1)))


def test_native_values_are_opaque_frozen_and_have_no_locator_field() -> None:
    bridge = NativeBridge(_id("nbrg", 1), "my-pa.native-source.v1", "Synthetic", WHEN)
    account = NativeSourceAccount(
        _id("nacct", 1),
        bridge.bridge_id,
        _id("src", 1),
        NativeSourceKind.MAIL,
        "Synthetic account",
        WHEN,
    )
    bucket = NativeSourceBucket(
        _id("nbkt", 1),
        account.account_id,
        None,
        NativeSourceKind.MAIL,
        "Synthetic mailbox",
        True,
        WHEN,
    )

    for model in (bridge, account, bucket):
        assert all("locator" not in field.name for field in fields(model))
    with pytest.raises(FrozenInstanceError):
        bucket.label = "changed"  # type: ignore[misc]


def test_exact_selection_is_nonempty_unique_and_canonical() -> None:
    assert _selection().bucket_ids == (_id("nbkt", 1), _id("nbkt", 2))
    with pytest.raises(ValueError, match="cannot be empty"):
        ExactBucketSelection(())
    with pytest.raises(ValueError, match="cannot repeat"):
        ExactBucketSelection((_id("nbkt", 1), _id("nbkt", 1)))


def test_exact_selection_digest_is_canonical_and_order_independent() -> None:
    expected = sha256(f"{_id('nbkt', 1)}\n{_id('nbkt', 2)}".encode()).hexdigest()
    revision = NativeConfigurationRevision(
        configuration_id=_id("ncfg", 1),
        revision=1,
        bridge_id=_id("nbrg", 1),
        timezone_name="UTC",
        start_date=date(2026, 8, 4),
        cutoff_at=WHEN,
        selection=_selection(),
        created_at=WHEN,
    )
    assert revision.selection_sha256 == expected


@pytest.mark.parametrize(
    ("timezone_name", "start_date", "expected_start"),
    [
        ("America/New_York", date(2026, 3, 8), datetime(2026, 3, 8, 5, tzinfo=UTC)),
        ("America/New_York", date(2026, 11, 1), datetime(2026, 11, 1, 4, tzinfo=UTC)),
        ("UTC", date(2026, 6, 1), datetime(2026, 6, 1, tzinfo=UTC)),
    ],
    ids=("spring-dst", "fall-dst", "non-dst-utc"),
)
def test_ac_009_timezone_dst_boundaries_are_deterministic(
    timezone_name: str,
    start_date: date,
    expected_start: datetime,
) -> None:
    revision = NativeConfigurationRevision(
        configuration_id=_id("ncfg", 1),
        revision=1,
        bridge_id=_id("nbrg", 1),
        timezone_name=timezone_name,
        start_date=start_date,
        cutoff_at=datetime(2026, 12, 1, 16, tzinfo=UTC),
        selection=_selection(),
        created_at=WHEN,
    )
    assert revision.start_at == expected_start
    assert revision.calendar_horizon_at == revision.cutoff_at + timedelta(days=90)


def test_ac_009_invalid_zone_and_start_after_cutoff_are_refused() -> None:
    with pytest.raises(ValueError, match="timezone is unknown"):
        NativeConfigurationRevision(
            configuration_id=_id("ncfg", 1),
            revision=1,
            bridge_id=_id("nbrg", 1),
            timezone_name="Not/A_Zone",
            start_date=date(2026, 8, 4),
            cutoff_at=WHEN,
            selection=_selection(),
            created_at=WHEN,
        )
    with pytest.raises(ValueError, match="start must not follow"):
        NativeConfigurationRevision(
            configuration_id=_id("ncfg", 1),
            revision=1,
            bridge_id=_id("nbrg", 1),
            timezone_name="UTC",
            start_date=date(2026, 8, 5),
            cutoff_at=WHEN,
            selection=_selection(),
            created_at=WHEN,
        )


def test_contact_membership_binds_group_contact_and_exact_version() -> None:
    membership = ContactMembership(
        _id("smem", 1),
        _id("nbkt", 1),
        _id("obj", 1),
        _id("ver", 1),
        WHEN,
    )
    assert membership.group_bucket_id != membership.contact_object_id
    assert membership.version_id == _id("ver", 1)


def test_checkpoint_predecessor_and_digest_are_structural() -> None:
    first = NativeCheckpoint(
        _id("ncp", 1),
        _id("nbkt", 1),
        1,
        None,
        "a" * 64,
        WHEN,
    )
    assert first.sequence == 1
    with pytest.raises(ValueError, match="predecessor"):
        NativeCheckpoint(
            _id("ncp", 2),
            _id("nbkt", 1),
            2,
            None,
            "b" * 64,
            WHEN,
        )


def test_simulation_states_are_closed_and_cannot_cross_the_live_gate() -> None:
    simulation = WatcherSimulation(
        _id("nsim", 1),
        _id("nbkt", 1),
        WatcherSimulationState.PENDING,
        1,
        WHEN,
    )
    running = simulation.transition(WatcherSimulationState.RUNNING, at=WHEN)
    complete = running.transition(WatcherSimulationState.COMPLETE, at=WHEN)
    receipt = SimulationReceipt(
        _id("nsimr", 1),
        complete.simulation_id,
        complete.state,
        _id("ncp", 1),
        WHEN,
    )
    gate = LiveActivationGate(
        _id("nlg", 1),
        complete.bucket_id,
        LiveActivationGateState.NOT_AUTHORIZED,
        WHEN,
    )

    assert receipt.terminal_state is WatcherSimulationState.COMPLETE
    assert gate.state is LiveActivationGateState.NOT_AUTHORIZED
    assert {state.value for state in WatcherSimulationState} == {
        "simulation_pending",
        "simulating",
        "simulation_complete",
        "simulation_failed",
    }
    assert {state.value for state in LiveActivationGateState} == {
        "not_authorized",
        "attestation_required",
        "blocked",
    }
    with pytest.raises(ValueError, match="not permitted"):
        complete.transition(WatcherSimulationState.RUNNING, at=WHEN)


def test_provider_and_object_vocabularies_are_explicitly_extended() -> None:
    assert {kind.value for kind in SourceProviderKind} == {
        "fixture",
        "apple_mail",
        "apple_calendar",
        "apple_contacts",
    }
    assert {kind.value for kind in ObjectKind} == {
        "file",
        "container",
        "mail_message",
        "calendar_event",
        "contact",
    }


def test_ac_039_source_provider_port_has_only_the_existing_read_surface() -> None:
    surface = {
        name
        for name, value in vars(SourceProvider).items()
        if getattr(value, "__isabstractmethod__", False)
        or (isinstance(value, property) and getattr(value.fget, "__isabstractmethod__", False))
    }
    assert surface == {"source_id", "list_children", "metadata", "fetch"}
    assert surface.isdisjoint({"create", "delete", "move", "rename", "update", "write"})


def test_ac_043_provider_envelopes_are_field_bounded_and_dependency_neutral() -> None:
    allowed_fields = {
        SourceObject: {
            "source_id",
            "source_object_id",
            "version_id",
            "kind",
            "media_type",
            "size_bytes",
            "modified_at",
        },
        SourceObjectContent: {
            "source_object_id",
            "version_id",
            "media_type",
            "content",
            "is_truncated",
        },
        NativeSourceAccount: {
            "account_id",
            "bridge_id",
            "source_id",
            "kind",
            "label",
            "observed_at",
        },
        NativeSourceBucket: {
            "bucket_id",
            "account_id",
            "parent_bucket_id",
            "kind",
            "label",
            "selectable",
            "observed_at",
        },
    }
    canonical_fields = {
        "assertion_id",
        "capture_id",
        "conversation_id",
        "person_id",
        "proposal_id",
        "relationship_id",
        "review_case_id",
    }
    for model, expected in allowed_fields.items():
        actual = {field.name for field in fields(model)}
        assert actual == expected
        assert actual.isdisjoint(canonical_fields)

    sources = (
        ROOT / "src/my_pa/domain/source/provider.py",
        ROOT / "src/my_pa/domain/native_sources/__init__.py",
        ROOT / "src/my_pa/domain/native_sources/models.py",
    )
    for path in sources:
        tree = ast.parse(path.read_text())
        dependencies = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not any(
            dependency.startswith(("my_pa.domain.capture", "my_pa.domain.relationship"))
            for dependency in dependencies
        ), path


def test_provider_router_retains_a_final_assert_never_exhaustiveness_guard() -> None:
    path = ROOT / "src/my_pa/infrastructure/providers/registered.py"
    tree = ast.parse(path.read_text())
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.Match)]
    assert len(matches) == 1
    final_case = matches[0].cases[-1]
    assert isinstance(final_case.pattern, ast.MatchAs)
    assert final_case.pattern.pattern is None and final_case.pattern.name is None
    calls = [
        node
        for statement in final_case.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Call)
    ]
    assert len(calls) == 1
    call = calls[0]
    assert isinstance(call.func, ast.Name) and call.func.id == "assert_never"
    assert len(call.args) == 1 and isinstance(call.args[0], ast.Name)
    assert call.args[0].id == "kind"
