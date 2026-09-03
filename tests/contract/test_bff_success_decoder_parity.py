"""Python success payloads and Vitest decoders agree on the same bytes.

`tests/contract/test_bff_gateway_contract_parity.py` is request parity: the BFF
and `normalize()` share one description of a `POST /v1/{capability}` document.
This module is the matching *success* lock. Vitest literals alone do not prove
that a Python view still dumps the shape a decoder accepts, so the payloads
here are built from the same models and handler key sets the gateway publishes,
committed under `web/src/lib/api/decode/fixtures/python/`, and re-checked
against a live `model_dump` / handler-identical dict on every run.

Nothing here opens a connection, reaches a source, or touches a database.
Identifiers are synthetic and follow `IdKind` shape only.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from my_pa.application.capabilities import build_capability_manifest, build_readiness_report
from my_pa.contracts.v1.capabilities import EffectiveLimits, ReadinessReport, ReadinessState
from my_pa.contracts.v1.capture import CaptureReceiptView
from my_pa.contracts.v1.commitments import CommitmentView
from my_pa.contracts.v1.reveal import RevealView
from my_pa.contracts.v1.tasks import TaskHistoryEntryView, TaskListEntry, TaskView
from my_pa.domain.capture.reveal import EvidenceGap, EvidenceState
from my_pa.domain.common.time import format_rfc3339
from my_pa.domain.identity.operation import Capability
from my_pa.domain.modeling.gate import ModelRoutePolicy
from my_pa.domain.situation.continuity import ContinuityAcceptanceKind, ContinuityEvidenceState
from my_pa.domain.task.history import TaskMutationAction, TaskMutationActor, TaskMutationOutcome
from my_pa.domain.task.lifecycle import TaskLifecycleState, TaskPriority

ROOT: Final = Path(__file__).resolve().parents[2]
FIXTURE_DIR: Final = ROOT / "web" / "src" / "lib" / "api" / "decode" / "fixtures" / "python"
SUCCESS_PATH: Final = FIXTURE_DIR / "success.json"

AT: Final = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)
DIGEST: Final = "a" * 64
LIMITS: Final = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)
WORKER_PLANE_UNAVAILABLE: Final = (
    "Worker-plane health is unavailable, stale, absent for queued work, or "
    "reports dead-lettered work; inspect worker_planes."
)


def _capture_create() -> dict[str, Any]:
    return CaptureReceiptView(
        receipt_id="rcpt_aaaaaaaa11111111",
        capture_id="cap_aaaaaaaa11111111",
        version_id="capver_aaaaaaaa11111111",
        version_number=1,
        idempotency_key="idem-1",
        content_sha256=DIGEST,
        issued_at=AT,
        created=True,
    ).model_dump(mode="json")


def _task_view() -> dict[str, Any]:
    return TaskView(
        task_id="tsk_aaaa0001aaaa0001aaaa0001",
        title="Check the pour",
        description=None,
        lifecycle_state=TaskLifecycleState.OPEN,
        evidence_state=ContinuityEvidenceState.ACCEPTED,
        origin_evidence_ref="asr_aaaa0001aaaa0001aaaa0001",
        closure_evidence_ref=None,
        accepted_by_review_decision_id=None,
        acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL,
        closure_history_id=None,
        version=1,
        priority=TaskPriority.P2,
        due_at=datetime(2026, 1, 2, tzinfo=UTC),
        scheduled_at=None,
        deferred_until=None,
        archived_at=None,
        project_id=None,
        situation_id=None,
        recurrence_id=None,
        opened_at=datetime(2026, 1, 1, tzinfo=UTC),
        closed_at=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        commitment_id=None,
        role=None,
    ).model_dump(mode="json")


def _task_list_entry() -> dict[str, Any]:
    return TaskListEntry(
        task_id="tsk_aaaa0001aaaa0001aaaa0001",
        title="Check the pour",
        lifecycle_state=TaskLifecycleState.OPEN,
        priority=TaskPriority.P2,
        due_at=datetime(2026, 1, 2, tzinfo=UTC),
        scheduled_at=None,
        deferred_until=None,
        archived_at=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        version=1,
    ).model_dump(mode="json")


def _task_history_entry() -> dict[str, Any]:
    return TaskHistoryEntryView(
        history_id="thst_aaaa0001aaaa0001aaaa0001",
        task_id="tsk_aaaa0001aaaa0001aaaa0001",
        action=TaskMutationAction.CREATE,
        actor=TaskMutationActor.PRINCIPAL,
        outcome=TaskMutationOutcome.APPLIED,
        before_version=0,
        after_version=1,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
    ).model_dump(mode="json")


def _reveal_unavailable() -> dict[str, Any]:
    return RevealView(
        subject_id="cap_aaaaaaaa11111111",
        subject_kind=None,
        state=EvidenceState.UNAVAILABLE,
        gap=EvidenceGap.SUBJECT_KIND_NOT_COVERED,
        capture_id=None,
        versions=(),
        spans=(),
        proposed=(),
        accepted=(),
        versions_with_completed_derivation=0,
    ).to_canonical_dict()


def _continuity_pulse() -> dict[str, Any]:
    """Handler-identical `_continuity_pulse` item keys (`attention_rank`, not `priority`)."""
    return {
        "pulse_items": [
            {
                "pulse_id": "puls_aaaaaaaa11111111",
                "item_type": "commitment",
                "item_ref": "cmt_aaaa0001aaaa0001aaaa0001",
                "reason_code": "commitment_overdue",
                "reason": "two days past its agreed moment",
                "basis_refs": ["asr_aaaa0001aaaa0001aaaa0001"],
                "consequence": None,
                "next_step": None,
                "attention_rank": 1,
                "generated_at": format_rfc3339(AT),
            }
        ]
    }


def _continuity_situations() -> dict[str, Any]:
    """Handler-identical `_continuity_situations` listing when workspace ports are absent."""
    return {
        "situations": [
            {
                "situation_id": "sit_aaaa0001aaaa0001aaaa0001",
                "title": "North pour",
                "state": "open",
                "description": None,
                "object_refs": ["cmt_aaaa0001aaaa0001aaaa0001"],
                "opened_at": format_rfc3339(datetime(2026, 1, 1, tzinfo=UTC)),
                "closed_at": None,
                "outcome": None,
            }
        ]
    }


def _review_decide() -> dict[str, Any]:
    """Decision payload keys from `ApplicationService` around the review receipt."""
    return {
        "review_case_id": "rvw_aaaaaaaa11111111",
        "decision_id": "rdec_aaaaaaaa11111111",
        "review_version": 1,
        "disposition": "correct_and_accept",
        "proposal_state": "corrected_accepted",
        "assertion_id": "asrt_aaaaaaaa11111111",
        "receipt_id": "rcpt_bbbbbbbb22222222",
    }


def _capabilities_get() -> dict[str, Any]:
    """`capabilities.get` handler shape: manifest, readiness, and worker planes."""
    manifest = build_capability_manifest(implemented=frozenset(Capability), limits=LIMITS)
    readiness = build_readiness_report(manifest, model_route=ModelRoutePolicy.DISABLED)
    worker_planes: list[dict[str, object]] = [
        {
            "plane": plane,
            "state": "unavailable",
            "backlog": None,
            "dead_lettered": None,
            "last_heartbeat_at": None,
        }
        for plane in ("capture", "enrollment")
    ]
    readiness = ReadinessReport(
        state=ReadinessState.DEGRADED,
        implemented_capabilities=readiness.implemented_capabilities,
        limitations=(*readiness.limitations, WORKER_PLANE_UNAVAILABLE),
    )
    return {
        "manifest": manifest.to_canonical_dict(),
        "readiness": readiness.to_canonical_dict(),
        "worker_planes": worker_planes,
    }


def _commitments_read() -> dict[str, Any]:
    """`CommitmentView.to_canonical_dict()` plus the handler's public wrapping."""
    view = CommitmentView(
        commitment_id="cmt_aaaa0001aaaa0001aaaa0001",
        direction="owed_to_principal",
        state="open",
        counterparty_person_id="per_aaaa0001aaaa0001aaaa0001",
        title="Send the drawing",
        description=None,
        due_date=datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
        created_at=datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        version=1,
        evidence_state="accepted",
        origin_evidence_ref="asr_aaaa0001aaaa0001aaaa0001",
        closure_evidence_ref=None,
        accepted_by_review_decision_id=None,
        closed_at=None,
    ).to_canonical_dict()
    view["counterparty"] = {
        "person_id": "per_aaaa0001aaaa0001aaaa0001",
        "display_name": "Synthetic B",
    }
    return {
        "commitment": view,
        "follow_up_task": None,
        "counterparty_options": [
            {
                "person_id": "per_aaaa0001aaaa0001aaaa0001",
                "display_name": "Synthetic B",
            }
        ],
        "counterparty_options_truncated": False,
    }


def python_success_payloads() -> dict[str, dict[str, Any]]:
    """Capability name → gateway `result` dict the matching Vitest decoder must accept."""
    return {
        "capture.create": _capture_create(),
        "tasks.read": {"task": _task_view()},
        "tasks.list": {"tasks": [_task_list_entry()]},
        "tasks.history": {"history": [_task_history_entry()]},
        "knowledge.reveal": _reveal_unavailable(),
        "continuity.pulse": _continuity_pulse(),
        "continuity.situations": _continuity_situations(),
        "review.decide": _review_decide(),
        "capabilities.get": _capabilities_get(),
        "commitments.read": _commitments_read(),
    }


def test_committed_python_fixtures_match_live_model_dumps() -> None:
    """A live Python dump still equals the bytes Vitest decodes, parsed as JSON."""
    assert SUCCESS_PATH.is_file(), f"committed Python fixtures missing at {SUCCESS_PATH}"
    committed = json.loads(SUCCESS_PATH.read_text(encoding="utf-8"))
    live = python_success_payloads()
    assert set(committed) == set(live)
    for capability, payload in live.items():
        assert payload == committed[capability], (
            f"{capability}: live Python dump drifted from the committed fixture"
        )


def test_dropping_a_required_array_is_not_the_committed_success() -> None:
    """A malformed-success regression is a different document than the committed one.

    Python cannot import the TypeScript decoder. Vitest `architecture.test.ts`
    already rejects `{}` for every capability, and `parity.test.ts` drops
    `pulse_items` from this same fixture and expects decode failure.
    """
    committed = json.loads(SUCCESS_PATH.read_text(encoding="utf-8"))
    pulse = dict(committed["continuity.pulse"])
    assert "pulse_items" in pulse
    pulse.pop("pulse_items")
    assert pulse != committed["continuity.pulse"]
    assert "pulse_items" not in pulse
