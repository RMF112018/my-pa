"""Reports Modernization WP06 (W3c): the transfer GC (`collect_report_transfers`, T19), FAST.

Over the `FakeUnitOfWork` (one per GC transaction) and a temporary
`FilesystemReportTransferStaging` + `FilesystemReportContentStore` on one
root, with sessions opened through the real service (W3b's rig):

* expiry of due open and finalized sessions, and the same run discarding
  their staging; terminal (aborted, consumed) staging left by a failed
  post-commit discard is discarded;
* orphans (staging with no session row) are reported, and discarded only
  with `discard_orphans`; unreadable entries are counted and never removed;
* bounded (`limit` per step, `more_remaining`) and idempotent (a second run
  does nothing); the `content` namespace is never touched;
* the operator command's usage refusal exits 1 (its database paths are in
  `tests/database/test_reports_transfer_consumption.py`).

All bytes are synthetic.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Final

import pytest
from apps.cli import report_content as report_content_cli

from my_pa.application.report_transfer_gc import TransferCollection, collect_report_transfers
from my_pa.contracts.ports import ReportTransferStaging
from my_pa.domain.reports.vocabulary import TransferState
from tests.conftest import WHEN, FakeUnitOfWork, Scene
from tests.unit.test_reports_transfer_application import (
    Rig,
    _abort,
    _consume,
    _finalize,
    _ok,
    _publish,
    _rig,
    _text,
    _uploaded,
)

LATER: Final = WHEN + timedelta(hours=2)


class _NoDiscard:
    """A staging whose post-commit discard fails, so terminal staging is left for the GC."""

    def __init__(self, inner: ReportTransferStaging) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def discard(self, session_id: str) -> bool:
        raise OSError("synthetic discard failure")


@pytest.fixture
def rig(scene: Scene, tmp_path: Path) -> Rig:
    return _rig(scene, tmp_path)


def _collect(rig: Rig, **kwargs: object) -> TransferCollection:
    assert rig.staging is not None
    world = rig.scene.world
    return collect_report_transfers(
        lambda: FakeUnitOfWork(world),
        rig.staging,
        now=kwargs.pop("now", LATER),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def _state(rig: Rig, session_id: str) -> TransferState:
    return rig.scene.world.report_transfer_sessions[session_id].state


def _plant_orphan(rig: Rig, session_id: str) -> None:
    assert rig.staging is not None
    data = b"synthetic orphan chunk"
    rig.staging.put_chunk(session_id, 0, chunk_sha256=hashlib.sha256(data).hexdigest(), data=data)


def test_due_sessions_expire_and_their_staging_is_discarded_in_the_same_run(rig: Rig) -> None:
    assert rig.staging is not None
    open_id = _uploaded(rig, _text(100), key="open")
    finalized_id = _uploaded(rig, _text(120), key="finalized")
    _ok(_finalize(rig, finalized_id))
    live_id = _uploaded(rig, _text(140), key="live", ttl_seconds=86_400)
    first = _collect(rig)
    assert first.summary() == {
        "expired": 2,
        "discarded": 2,
        "orphans_found": 0,
        "orphans_discarded": 0,
        "orphans_remaining": 0,
        "unreadable": 0,
        "more_remaining": False,
    }
    print("TRANSFER_GC_SUMMARY", first.summary())
    assert first.clean
    assert _state(rig, open_id) is TransferState.EXPIRED
    assert _state(rig, finalized_id) is TransferState.EXPIRED
    assert _state(rig, live_id) is TransferState.OPEN
    assert not rig.staging.has_session(open_id) and not rig.staging.has_session(finalized_id)
    assert rig.staging.has_session(live_id)
    # Idempotent: nothing more to do.
    again = _collect(rig)
    assert (again.expired, again.discarded, again.clean) == (0, 0, True)
    # Not yet due at the request clock: nothing expires.
    assert _collect(rig, now=WHEN).expired == 0


def test_terminal_staging_left_by_a_failed_discard_is_collected(
    scene: Scene, tmp_path: Path
) -> None:
    real = _rig(scene, tmp_path)
    assert real.staging is not None
    failing = _rig(scene, tmp_path, staging_override=_NoDiscard(real.staging))  # type: ignore[arg-type]
    aborted = _uploaded(failing, _text(200), key="aborted")
    _ok(_abort(failing, aborted))
    consumed = _uploaded(failing, _text(210), key="consumed")
    token = _ok(_finalize(failing, consumed))["content_token"]
    _publish(  # W3b's helper asserts success
        failing,
        {"transfer": {"session_id": consumed, "content_token": token}},
        "consumer",
    )
    other = _uploaded(failing, _text(220), key="other")
    _ok(_finalize(failing, other))
    _consume(failing, other)  # a consumed row (state only) whose staging remains
    assert all(real.staging.has_session(s) for s in (aborted, consumed, other))
    objects = real.store.stored_object_ids() if real.store is not None else ()
    collected = _collect(real, now=WHEN)
    assert (collected.expired, collected.discarded) == (0, 3)
    assert not any(real.staging.has_session(s) for s in (aborted, consumed, other))
    assert _state(real, consumed) is TransferState.CONSUMED
    # The content namespace is never touched.
    assert (real.store.stored_object_ids() if real.store is not None else ()) == objects


def test_orphans_are_reported_and_discarded_only_on_request(rig: Rig) -> None:
    assert rig.staging is not None and rig.store is not None
    _publish(rig, {"format": "text", "body": "synthetic content object"}, "content")
    objects = rig.store.stored_object_ids()
    orphan = "grxfr_" + "0" * 32
    _plant_orphan(rig, orphan)
    reported = _collect(rig)
    assert (reported.orphans_found, reported.orphans_discarded) == (1, 0)
    assert reported.orphans_remaining == 1 and not reported.clean
    assert rig.staging.has_session(orphan)
    removed = _collect(rig, discard_orphans=True)
    assert (removed.orphans_found, removed.orphans_discarded, removed.clean) == (1, 1, True)
    assert not rig.staging.has_session(orphan)
    assert rig.store.stored_object_ids() == objects
    assert _collect(rig, discard_orphans=True).orphans_found == 0


def test_unreadable_entries_are_counted_and_never_removed(rig: Rig) -> None:
    junk = rig.root / "transfer" / "not-a-shard"
    junk.parent.mkdir(parents=True, exist_ok=True)
    junk.write_bytes(b"synthetic junk")
    collected = _collect(rig, discard_orphans=True)
    assert collected.unreadable >= 1 and not collected.clean
    assert junk.exists()


def test_every_step_is_bounded_by_the_limit(rig: Rig) -> None:
    assert rig.staging is not None
    sessions = [_uploaded(rig, _text(50 + i), key=f"due-{i}") for i in range(3)]
    orphans = ["grxfr_" + str(i) * 32 for i in range(1, 4)]
    for orphan in orphans:
        _plant_orphan(rig, orphan)
    first = _collect(rig, limit=1, discard_orphans=True)
    assert (first.expired, first.discarded, first.orphans_discarded) == (1, 1, 1)
    assert first.more_remaining and not first.clean
    runs = [first]
    while not runs[-1].clean:
        runs.append(_collect(rig, limit=1, discard_orphans=True))
        assert len(runs) < 10
    assert sum(run.expired for run in runs) == 3
    assert sum(run.discarded for run in runs) == 3
    assert sum(run.orphans_discarded for run in runs) == 3
    assert all(_state(rig, s) is TransferState.EXPIRED for s in sessions)
    assert rig.staging.staged_session_ids() == ()


@pytest.mark.parametrize("limit", [0, 1001, "10", True])
def test_the_limit_is_validated(rig: Rig, limit: object) -> None:
    with pytest.raises(ValueError, match="limit"):
        _collect(rig, limit=limit)


@pytest.mark.parametrize(
    "arguments",
    [
        ["transfer-gc", "--limit", "many"],
        ["transfer-gc", "--unknown"],
    ],
)
def test_the_operator_command_refuses_usage_errors_with_exit_1(arguments: list[str]) -> None:
    assert report_content_cli.main(arguments) == report_content_cli.EXIT_REFUSED


@pytest.mark.parametrize(
    "arguments",
    [
        ["preservation-verify", "--unknown"],
        ["--unknown", "preservation-verify"],
    ],
)
def test_preservation_verify_usage_errors_are_refusals(arguments: list[str]) -> None:
    assert report_content_cli.main(arguments) == report_content_cli.EXIT_REFUSED


@pytest.mark.parametrize(
    "arguments",
    [
        # WP08 (WP05b corrective n3): the literal name as a value or a stray
        # argument of another subcommand does not select the remap.
        ["verify", "--unknown", "preservation-verify"],
        ["verify", "--principal", "preservation-verify", "--unknown"],
        ["backup", "--principal", "prn_x", "--destination", "transfer-gc", "--unknown"],
        ["no-such-command", "preservation-verify"],
    ],
)
def test_other_subcommands_keep_argparses_usage_exit_2(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        report_content_cli.main(arguments)
    assert stopped.value.code == 2
