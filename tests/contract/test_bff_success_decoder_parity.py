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


def _reports_read() -> dict[str, Any]:
    """Handler-identical `_reports_read` keys, including optional structured_content."""
    return {
        "report_id": "rpt_aaaaaaaa11111111",
        "report_run_id": "rrun_aaaaaaaa11111111",
        "cycle_run_id": "micr_aaaaaaaa11111111",
        "focus_area_id": "communications",
        "stage": "collector",
        "artifact_kind": "collector_candidates",
        "source_lane": None,
        "report_date": "2026-08-20",
        "title": "E2E morning brief collector",
        "artifact_state": "final",
        "content_sha256": DIGEST,
        "content_bytes": 48,
        "committed_at": format_rfc3339(AT),
        "version": 1,
        "supersedes_report_id": None,
        "dependency_report_ids": [],
        "provenance": [
            {
                "source_system": "synthetic",
                "source_ref": "src_aaaaaaaa11111111",
                "relation": "supports",
                "source_url": None,
            }
        ],
        "body_markdown": "# Morning Brief\n\n- scraped item one",
        "structured_content": {"lane": "persisted", "marker": "not-from-markdown"},
    }


def _reports_latest() -> dict[str, Any]:
    """Handler-identical `_reports_latest` current-head selection."""
    return {
        "report_id": "rpt_aaaaaaaa11111111",
        "cycle_run_id": "micr_aaaaaaaa11111111",
        "stage": "collector",
        "artifact_kind": "collector_candidates",
        "focus_area_id": "communications",
        "source_lane": None,
        "content_sha256": DIGEST,
        "artifact_state": "final",
    }


def _reports_list() -> dict[str, Any]:
    """Handler-identical `_reports_list` page, including required next_cursor."""
    return {
        "items": [
            {
                "report_id": "rpt_aaaaaaaa11111111",
                "cycle_run_id": "micr_aaaaaaaa11111111",
                "stage": "collector",
                "artifact_kind": "collector_candidates",
                "focus_area_id": "communications",
                "source_lane": None,
                "title": "E2E morning brief collector",
                "content_sha256": DIGEST,
                "artifact_state": "final",
            }
        ],
        "next_cursor": None,
    }


def _reports_search() -> dict[str, Any]:
    """Handler-identical `_reports_search` lexical matches."""
    return {
        "items": [
            {
                "report_id": "rpt_aaaaaaaa11111111",
                "title": "E2E morning brief collector",
                "snippet": "morning brief",
                "cycle_run_id": "micr_aaaaaaaa11111111",
                "stage": "collector",
                "artifact_kind": "collector_candidates",
            }
        ]
    }


def _reports_resolve_set() -> dict[str, Any]:
    """Handler-identical `resolve_set` payload: aggregate plus per-member states."""
    return {
        "cycle_run_id": "micr_aaaaaaaa11111111",
        "cycle_id": "morning_intelligence",
        "business_date": "2026-08-20",
        "set_id": "morning_brief_inputs",
        "aggregate": "BLOCKED",
        "members": [
            {
                "member_id": "communications",
                "focus_area_id": "communications",
                "source_lane": None,
                "readiness": "MISSING",
                "required": True,
                "artifact_id": None,
                "producer_run_id": None,
                "content_sha256": None,
                "committed_at": None,
                "readiness_reason": "missing",
            }
        ],
    }


def _stamp() -> str:
    return format_rfc3339(AT)


def _entity_id() -> str:
    return "ent_aaaaaaaa11111111"


def _entity_view_payload() -> dict[str, Any]:
    stamped = _stamp()
    return {
        "entity_id": _entity_id(),
        "entity_type": "person",
        "canonical_name": "pat synthetic",
        "display_name": "Pat Synthetic",
        "status": "active",
        "created_at": stamped,
        "updated_at": stamped,
        "version": 1,
        "superseded_by_entity_id": None,
    }


def _entity_summary_payload() -> dict[str, Any]:
    return {
        "entity_id": _entity_id(),
        "entity_type": "person",
        "canonical_name": "pat synthetic",
        "display_name": "Pat Synthetic",
        "status": "active",
        "affiliated_organizations": ["Acme Synthetic"],
        "project_roles": ["architect"],
    }


def _lifecycle_identifier_payload() -> dict[str, Any]:
    return {
        "identifier_id": "xid_aaaaaaaa11111111",
        "namespace": "email",
        "display_value": "pat.synthetic@example.test",
        "verified": False,
        "effective_from": None,
        "effective_to": None,
        "state": "active",
        "version": 1,
        "retired_at": None,
        "updated_at": _stamp(),
        "superseded_by_identifier_id": None,
    }


def _lifecycle_alias_payload() -> dict[str, Any]:
    return {
        "alias_id": "eals_aaaaaaaa11111111",
        "alias_type": "full_name",
        "display_value": "Patricia Synthetic",
        "effective_from": None,
        "effective_to": None,
        "state": "active",
        "version": 1,
        "retired_at": None,
        "updated_at": _stamp(),
        "superseded_by_alias_id": None,
    }


def _assignment_payload() -> dict[str, Any]:
    return {
        "assignment_id": "asn_aaaaaaaa11111111",
        "entity_id": _entity_id(),
        "assignment_type": "employment",
        "scope_entity_id": "ent_bbbbbbbb22222222",
        "role": "architect",
        "discipline": None,
        "responsibility_class": None,
        "status": "active",
        "is_current": True,
        "effective_from": None,
        "effective_to": None,
        "version": 1,
    }


def _relationship_payload() -> dict[str, Any]:
    return {
        "relationship_id": "erel_aaaaaaaa11111111",
        "is_current": True,
        "from_entity_id": _entity_id(),
        "relationship_type": "works_for",
        "to_entity_id": "ent_bbbbbbbb22222222",
        "scope_entity_id": None,
        "state": "active",
        "effective_from": None,
        "effective_to": None,
        "version": 1,
    }


def _unresolved_mention_payload() -> dict[str, Any]:
    stamped = _stamp()
    return {
        "observation_id": "eobs_aaaaaaaa11111111",
        "kind": "document_mention",
        "mention_display_name": "Pat",
        "source_id": "src_aaaaaaaa11111111",
        "source_object_id": "obj_aaaaaaaa11111111",
        "source_version_id": "ver_aaaaaaaa11111111",
        "observed_at": stamped,
        "recorded_at": stamped,
    }


def _recorded_observation_payload() -> dict[str, Any]:
    stamped = _stamp()
    return {
        "observation_id": "eobs_aaaaaaaa11111111",
        "kind": "contact_record",
        "authority": "source_observation",
        "origin": "configured_source",
        "state": "current",
        "state_reason": None,
        "mention_display_name": "Pat",
        "source_id": "src_aaaaaaaa11111111",
        "source_object_id": "obj_aaaaaaaa11111111",
        "source_version_id": "ver_aaaaaaaa11111111",
        "entity_id": _entity_id(),
        "superseded_by_observation_id": None,
        "resolution_version": 0,
        "observed_at": stamped,
        "recorded_at": stamped,
    }


def _entity_name_payload() -> dict[str, Any]:
    return {
        "entity_name_id": "enam_aaaaaaaa11111111",
        "entity_id": _entity_id(),
        "name_type_code": "display",
        "display_value": "Pat Synthetic",
        "normalized_value": "pat synthetic",
        "is_preferred": True,
        "effective_from": None,
        "effective_to": None,
        "state": "active",
        "version": 1,
        "updated_at": _stamp(),
        "retired_at": None,
        "superseded_by_entity_name_id": None,
    }


def _entity_address_payload() -> dict[str, Any]:
    return {
        "entity_address_id": "eadr_aaaaaaaa11111111",
        "entity_id": _entity_id(),
        "address_type_code": "office",
        "raw_value": "1 Synthetic Way",
        "normalized_address_value": "1 synthetic way",
        "line1": "1 Synthetic Way",
        "line2": None,
        "city": None,
        "region": None,
        "postal_code": None,
        "country": None,
        "label": None,
        "is_preferred": False,
        "effective_from": None,
        "effective_to": None,
        "state": "active",
        "version": 1,
        "updated_at": _stamp(),
        "retired_at": None,
        "superseded_by_entity_address_id": None,
    }


def _communication_method_payload() -> dict[str, Any]:
    return {
        "communication_method_id": "ecmm_aaaaaaaa11111111",
        "entity_id": _entity_id(),
        "method_type_code": "email",
        "usage_context_code": "corporate",
        "display_value": "pat.synthetic@example.test",
        "normalized_value": "pat.synthetic@example.test",
        "verification_status_code": "unresolved",
        "is_preferred": True,
        "effective_from": None,
        "effective_to": None,
        "state": "active",
        "version": 1,
        "updated_at": _stamp(),
        "retired_at": None,
        "superseded_by_communication_method_id": None,
        "linked_external_identifier_id": None,
    }


def _participation_payload() -> dict[str, Any]:
    return {
        "participation_id": "eppt_aaaaaaaa11111111",
        "project_entity_id": "ent_cccccccccccccccc33333333",
        "participant_entity_id": _entity_id(),
        "project_display_name": "North Pour",
        "role_basis_code": "unresolved",
        "stakeholder_side_code": "design",
        "stakeholder_class_code": "unresolved",
        "relationship_status_code": "active",
        "role_code": None,
        "role_text": "architect",
        "discipline_code": None,
        "discipline_text": None,
        "scope_text": None,
        "effective_from": None,
        "effective_to": None,
        "state": "active",
        "version": 1,
        "updated_at": _stamp(),
        "retired_at": None,
        "superseded_by_participation_id": None,
    }


def _identity_history_entry_payload() -> dict[str, Any]:
    return {
        "history_id": "emut_aaaaaaaa11111111",
        "occurred_at": _stamp(),
        "source": "direct_mutation",
        "operation": "entities.create",
        "involved_entity_ids": [_entity_id()],
        "changes": [
            {
                "family": "entity",
                "record_id": _entity_id(),
                "effect_kind": "create",
                "before_state": None,
                "after_state": {"display_name": "Pat Synthetic"},
            }
        ],
        "actor_class": "user",
        "actor_id": "prn_aaaaaaaa11111111",
        "authority": None,
        "correlation_id": None,
        "audit_id": "audit_aaaaaaaa11111111",
        "reason": None,
        "source_identity_operation_id": None,
        "receipt_id": None,
    }


def _entity_profile_payload() -> dict[str, Any]:
    return {
        "entity": _entity_view_payload(),
        "assembled_at": _stamp(),
        "limitations": [],
        "is_complete": True,
        "organization_profile": None,
        "names": [_entity_name_payload()],
        "addresses": [],
        "communication_methods": [],
        "participations_as_project": [],
        "participations_as_participant": [],
        "affiliations_as_person": [],
        "affiliations_as_organization": [],
    }


def _entity_context_card_payload() -> dict[str, Any]:
    return {
        "entity": _entity_view_payload(),
        "assembled_at": _stamp(),
        "coverage": [],
        "most_recent_observation_at": None,
        "limitations": ["no_source_has_been_observed", "the_memory_plane_is_unavailable"],
        "is_complete": True,
        "aliases": [],
        "identifiers": [],
        "assignments": [],
        "relationships": [],
        "observations": [],
        "memories": [],
    }


def python_success_payloads() -> dict[str, dict[str, Any]]:
    """Capability name → gateway `result` dict the matching Vitest decoder must accept."""
    entity_id = _entity_id()
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
        "reports.read": _reports_read(),
        "reports.latest": _reports_latest(),
        "reports.list": _reports_list(),
        "reports.search": _reports_search(),
        "reports.resolve_set": _reports_resolve_set(),
        "entities.search": {"entities": [_entity_summary_payload()]},
        "entities.get": {"entity": _entity_view_payload()},
        "entities.resolve": {
            "resolution": {
                "outcome": "ambiguous",
                "entity_id": None,
                "candidates": [
                    {
                        "entity_id": entity_id,
                        "entity_type": "person",
                        "display_name": "Alex Chen",
                        "status": "active",
                        "superseded_by_entity_id": None,
                        "matched_on": ["canonical_name"],
                        "signals": [],
                    }
                ],
                "warnings": ["several_entities_share_this_name"],
                "candidates_were_truncated": False,
            }
        },
        "entities.context": {"context_card": _entity_context_card_payload()},
        "entities.relationships": {"relationships": [_relationship_payload()]},
        "entities.unresolved_mentions": {"mentions": [_unresolved_mention_payload()]},
        "entities.identifiers.list": {
            "entity_id": entity_id,
            "identifiers": [_lifecycle_identifier_payload()],
        },
        "entities.aliases.list": {"entity_id": entity_id, "aliases": [_lifecycle_alias_payload()]},
        "entities.assignments.list": {"assignments": [_assignment_payload()]},
        "entities.observations.list": {"observations": [_recorded_observation_payload()]},
        "entities.identity_history": {
            "entity_id": entity_id,
            "entries": [_identity_history_entry_payload()],
            "is_truncated": False,
            "next_cursor": None,
            "audit_id": "audit_aaaaaaaa11111111",
        },
        "entities.profile": {"profile": _entity_profile_payload()},
        "entities.names.list": {"entity_id": entity_id, "names": [_entity_name_payload()]},
        "entities.addresses.list": {"entity_id": entity_id, "addresses": [_entity_address_payload()]},
        "entities.communication.list": {
            "entity_id": entity_id,
            "communication_methods": [_communication_method_payload()],
        },
        "entities.participations.list": {
            "entity_id": entity_id,
            "perspective": "participant",
            "participations": [_participation_payload()],
        },
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
