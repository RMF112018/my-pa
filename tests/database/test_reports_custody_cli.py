"""Reports Modernization WP05b Part C (11): the operator custody capabilities over the CLI.

End to end through `apps/cli/invoke.py`'s `main` -- `load_settings`, the real
`build_gateway_runtime` composition, `adapters.cli.run` (which stamps
`OperatorSurface.CLI`), `ApplicationService`, the PostgreSQL repository and a
real filesystem report content store under `tmp_path` -- against a disposable
current-head clone whose URL the fixture puts in the environment:

* `reports.publish`, then `reports.hold.place`: the sealed preservation copy is
  re-verified on disk (`verify_preservation_copy`) from the hold row;
* while held, `reports.delete` is refused with exactly `denied [report_held]`
  and writes no lifecycle row; archive, restore and update are allowed, and
  `reports.read` answers `"held": true`;
* `reports.retention.get` (no policy) -> `reports.retention.set` 5 years ->
  `reports.retention.get` shows the history (old unset, new 5 years) and the
  report's eligibility (`held`);
* `reports.hold.release`, then `reports.delete` succeeds, and the eligibility
  is `retention_running` from the trash event;
* with no `MY_PA_REPORT_CONTENT_ROOT`, a placement is `unavailable
  [preservation_store]` and writes no hold row;
* the same capability invoked on the composed service without the operator
  surface (the stdio MCP shape: no `operator_surface` stamp) is `denied` and
  writes no hold or retention row.

Every title, body and identifier is synthetic. Nothing is purged or deleted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli import invoke as invoke_cli
from sqlalchemy import Engine, text

from my_pa.adapters.normalization import normalize
from my_pa.application.report_preservation import verify_preservation_copy
from my_pa.bootstrap.gateway import build_gateway_runtime, report_preservation_store
from my_pa.bootstrap.settings import load_settings
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.infrastructure.persistence.reports import SqlGeneralReportRepository

pytestmark = pytest.mark.database

REQUESTED_AT: Final = "2026-11-06T12:00:00Z"
_DENIED: Final = "the request is not permitted for this principal, purpose, and scope"
_UNAVAILABLE: Final = "the requested evidence is temporarily unavailable"


def _principal_id() -> str:
    runtime = build_gateway_runtime(load_settings())
    try:
        assert runtime.principal is not None
        return runtime.principal.principal_id
    finally:
        runtime.close()


def _cli(
    capsys: pytest.CaptureFixture[str],
    principal_id: str,
    capability: Capability,
    payload: dict[str, Any],
    tag: str,
) -> tuple[int, dict[str, Any]]:
    """`apps/cli/invoke.py <capability> ...`: the exit status and the rendered envelope."""
    (purpose,) = permitted_purposes(capability)
    status = invoke_cli.main(
        [
            capability.value,
            "--request-id",
            f"req-custody-{tag}",
            "--purpose",
            purpose.value,
            "--principal-id",
            principal_id,
            "--requested-at",
            REQUESTED_AT,
            "--payload",
            json.dumps(payload),
        ]
    )
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1, out
    return status, json.loads(out[0])


def _ok(answer: tuple[int, dict[str, Any]]) -> dict[str, Any]:
    status, document = answer
    assert document["error"] is None, document["error"]
    assert status == 0
    result = document["result"]
    assert isinstance(result, dict)
    return result


def _refused(answer: tuple[int, dict[str, Any]]) -> str:
    """The refusal as an operator reads it: `code [detail, ...]`."""
    status, document = answer
    assert status != 0 and document["result"] is None
    error = document["error"]
    return f"{error['code']} [{', '.join(error['safe_details'])}]"


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(text(f"SELECT count(*) FROM knowledge.{table}")).scalar_one()  # noqa: S608
        )


def _hold(report_id: str, revision: int, key: str) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "expected_hold_revision": revision,
        "reason": "Synthetic litigation hold.",
        "idempotency_key": key,
    }


def _move(report_id: str, revision: int, key: str) -> dict[str, Any]:
    return {"report_id": report_id, "expected_lifecycle_revision": revision, "idempotency_key": key}


def _publish(capsys: pytest.CaptureFixture[str], principal_id: str, tag: str) -> str:
    published = _ok(
        _cli(
            capsys,
            principal_id,
            Capability.REPORTS_PUBLISH,
            {
                "title": f"Synthetic custody report {tag}",
                "content": {"format": "markdown", "body": "# Synthetic\n\nCustody body."},
                "idempotency_key": f"custody-publish-{tag}",
            },
            f"publish-{tag}",
        )
    )
    return str(published["report_id"])


def test_hold_retention_and_release_end_to_end_over_the_cli(
    migrated_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "report-content"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("MY_PA_REPORT_CONTENT_ROOT", str(root))
    principal_id = _principal_id()
    report_id = _publish(capsys, principal_id, "held")

    placed = _ok(
        _cli(capsys, principal_id, Capability.REPORTS_HOLD_PLACE, _hold(report_id, 0, "hp"), "hp")
    )
    assert placed["held"] is True and placed["hold_revision"] == 1
    assert placed["preservation"]["object_count"] == 1
    assert placed["preservation"]["version_count"] == 1
    # The sealed copy is re-verified on disk from the hold row the CLI wrote.
    with migrated_engine.connect() as connection:
        events = SqlGeneralReportRepository(connection).hold_events(
            report_id, principal_id=principal_id
        )
    assert events is not None and len(events) == 1
    (event,) = events
    assert event.event_id == placed["event_id"]
    assert event.authority.authority_class == "local_operator"
    assert event.authority.decision_channel == "local_cli"
    assert event.preservation is not None
    assert event.preservation.seal_sha256 == placed["preservation"]["seal_sha256"]
    store = report_preservation_store(load_settings(), migrated_engine)
    assert store is not None
    assert verify_preservation_copy(store, event) >= 1
    assert any(path.is_file() for path in root.rglob("*"))

    # H2: the hold refuses trashing, and only trashing.
    lifecycle_rows = _count(migrated_engine, "report_lifecycle_events")
    refusal = _cli(capsys, principal_id, Capability.REPORTS_DELETE, _move(report_id, 0, "d1"), "d1")
    assert _refused(refusal) == "denied [report_held]"
    assert refusal[1]["error"]["message"] == _DENIED
    assert _count(migrated_engine, "report_lifecycle_events") == lifecycle_rows
    _ok(_cli(capsys, principal_id, Capability.REPORTS_ARCHIVE, _move(report_id, 0, "a1"), "a1"))
    _ok(_cli(capsys, principal_id, Capability.REPORTS_RESTORE, _move(report_id, 1, "r1"), "r1"))
    updated = _ok(
        _cli(
            capsys,
            principal_id,
            Capability.REPORTS_UPDATE,
            {
                "report_id": report_id,
                "expected_version": 1,
                "patch": {"title": "Synthetic custody report, revised while held"},
                "change_reason": "Synthetic revision under hold.",
                "idempotency_key": "u1",
            },
            "u1",
        )
    )
    assert updated["version_number"] == 2
    read = _ok(_cli(capsys, principal_id, Capability.REPORTS_READ, {"report_id": report_id}, "rd"))
    assert read["held"] is True

    # H3: retention, unset by default; a change is appended with old and new.
    unset = _ok(
        _cli(capsys, principal_id, Capability.REPORTS_RETENTION_GET, {"report_id": report_id}, "g0")
    )
    assert unset["policy"] is None and unset["history"] == []
    assert unset["eligibility"]["reason"] == "no_policy"
    changed = _ok(
        _cli(
            capsys,
            principal_id,
            Capability.REPORTS_RETENTION_SET,
            {
                "expected_policy_revision": 0,
                "reason": "Synthetic five-year policy.",
                "idempotency_key": "rs1",
                "period": {"count": 5, "unit": "years"},
            },
            "rs1",
        )
    )
    assert changed["policy_revision"] == 1 and changed["previous_period"] is None
    assert changed["period"] == {"count": 5, "unit": "years"}
    policy = _ok(
        _cli(capsys, principal_id, Capability.REPORTS_RETENTION_GET, {"report_id": report_id}, "g1")
    )
    assert policy["policy"]["policy_revision"] == 1
    assert policy["policy"]["period"] == {"count": 5, "unit": "years"}
    (entry,) = policy["history"]
    assert entry["previous_period"] is None
    assert entry["period"] == {"count": 5, "unit": "years"}
    assert entry["decision_channel"] == "local_cli"
    assert policy["eligibility"]["report_id"] == report_id
    assert policy["eligibility"]["reason"] == "held"
    assert policy["eligibility"]["eligible"] is False

    released = _ok(
        _cli(capsys, principal_id, Capability.REPORTS_HOLD_RELEASE, _hold(report_id, 1, "hr"), "hr")
    )
    assert released["held"] is False and released["hold_revision"] == 2
    # The preservation copy is kept after release.
    assert verify_preservation_copy(store, event) >= 1
    deleted = _ok(
        _cli(capsys, principal_id, Capability.REPORTS_DELETE, _move(report_id, 2, "d2"), "d2")
    )
    assert deleted["lifecycle_state"] == "trashed"
    after = _ok(
        _cli(capsys, principal_id, Capability.REPORTS_RETENTION_GET, {"report_id": report_id}, "g2")
    )
    assert after["eligibility"]["reason"] == "retention_running"
    assert after["eligibility"]["clock_start"] is not None
    assert after["eligibility"]["eligible_at"] is not None
    assert _count(migrated_engine, "report_hold_events") == 2
    assert _count(migrated_engine, "report_retention_policy_events") == 1


def test_place_without_a_store_root_is_refused_and_writes_no_hold(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("MY_PA_REPORT_CONTENT_ROOT", raising=False)
    principal_id = _principal_id()
    report_id = _publish(capsys, principal_id, "storeless")
    refusal = _cli(
        capsys, principal_id, Capability.REPORTS_HOLD_PLACE, _hold(report_id, 0, "hp"), "hp"
    )
    assert _refused(refusal) == "unavailable [preservation_store]"
    assert refusal[1]["error"]["message"] == _UNAVAILABLE
    assert _count(migrated_engine, "report_hold_events") == 0


@pytest.mark.parametrize(
    "capability",
    [
        Capability.REPORTS_HOLD_PLACE,
        Capability.REPORTS_HOLD_RELEASE,
        Capability.REPORTS_RETENTION_SET,
        Capability.REPORTS_RETENTION_GET,
    ],
    ids=lambda capability: capability.value,
)
def test_without_the_operator_surface_the_composed_service_denies(
    migrated_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    capability: Capability,
) -> None:
    """The stdio MCP shape: the same composed service, no `operator_surface` stamp."""
    root = tmp_path / "report-content"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("MY_PA_REPORT_CONTENT_ROOT", str(root))
    principal_id = _principal_id()
    report_id = _publish(capsys, principal_id, "unstamped")
    payloads: dict[Capability, dict[str, Any]] = {
        Capability.REPORTS_HOLD_PLACE: _hold(report_id, 0, "hp"),
        Capability.REPORTS_HOLD_RELEASE: _hold(report_id, 1, "hr"),
        Capability.REPORTS_RETENTION_SET: {
            "expected_policy_revision": 0,
            "reason": "Synthetic.",
            "idempotency_key": "rs",
            "period": {"count": 5, "unit": "years"},
        },
        Capability.REPORTS_RETENTION_GET: {"report_id": report_id},
    }
    (purpose,) = permitted_purposes(capability)
    metadata, command = normalize(
        capability.value,
        {
            "request_id": "req-unstamped",
            "purpose": purpose.value,
            "principal_id": principal_id,
            "requested_at": REQUESTED_AT,
            "payload": payloads[capability],
        },
    )
    runtime = build_gateway_runtime(load_settings())
    try:
        assert runtime.principal is not None
        envelope = runtime.service.invoke(metadata, command, principal=runtime.principal)
    finally:
        runtime.close()
    assert envelope.result is None and envelope.error is not None
    assert envelope.error.code.value == "denied"
    assert list(envelope.error.safe_details) == []
    assert _count(migrated_engine, "report_hold_events") == 0
    assert _count(migrated_engine, "report_retention_policy_events") == 0
    assert not any(path.is_file() for path in root.rglob("*"))
