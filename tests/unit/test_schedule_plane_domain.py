"""Schedule Scenarios S6-2: the pure plane domain and vocabulary (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` sections 14.2,
14.7 and 14.11.1: the 8 identifier kinds against S6-1's patterns, the enum
lockstep, the import request's 4 added fields and invariants, the `v1`/`v2`
digest golden vectors, the intake Series name, the second-admission key, the
writer bucket, the provenance sets against the lineage vocabulary, and the
lineage storage vocabulary against the public one. Every value is synthetic.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any, Final

import pytest

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.lineage import vocabulary as lineage
from my_pa.domain.schedule import (
    ScheduleBaselineKind,
    ScheduleImportApproval,
    ScheduleImportRequest,
    SchedulePublicationRole,
    canonical_json_bytes,
    normalize_series_name,
    plane,
    schedule_import_request_digest,
)
from my_pa.domain.schedule.baselines import BaselineType
from my_pa.domain.schedule.scenario import outputs
from my_pa.domain.schedule.series_match import MatchOutcome

P: Final = "prn_s62domain0001"
PRJ: Final = "prj_s62domain0001"
SER: Final = "sser_s62domain0001"
ENR: Final = "enr_s62domain0001"
OBJ: Final = "obj_s62domain0001"
VER: Final = "ver_s62domain0001"
DECISION: Final = "ssmd_s62domain0001"
APPROVAL: Final = ScheduleImportApproval(
    approval_reference="Contract award letter 7",
    effective_from=date(2026, 6, 1),
    reason="Synthetic approved baseline",
)


def _request(**overrides: object) -> ScheduleImportRequest:
    fields: dict[str, Any] = {
        "project_id": PRJ,
        "series_id": None,
        "series_name": normalize_series_name("Synthetic Master Schedule"),
        "enrollment_id": ENR,
        "source_object_id": OBJ,
        "source_version_id": VER,
        "publication_role": SchedulePublicationRole.UPDATE,
        "baseline_kind": None,
        "expected_data_date": date(2026, 5, 4),
        "supersedes_publication_id": None,
        "idempotency_key": "synthetic-key-0001",
    }
    fields.update(overrides)
    return ScheduleImportRequest(**fields)


def _auto(**overrides: object) -> ScheduleImportRequest:
    return _request(**{"series_name": None, "series_auto": True, **overrides})


def _approved(**overrides: object) -> ScheduleImportRequest:
    return _request(
        **{
            "publication_role": SchedulePublicationRole.BASELINE,
            "baseline_kind": ScheduleBaselineKind.CONTRACT,
            "approval": APPROVAL,
            **overrides,
        }
    )


# ---- identifiers (section 14.2) --------------------------------------------------


def test_the_eight_prefixes_are_s61s_patterns() -> None:
    """S6-1's `sscv_`/`scpm_` patterns name exactly the S6-2 identifier kinds."""
    assert outputs._VERSION_ID.pattern.startswith(rf"\A{IdKind.SCHEDULE_SCENARIO_VERSION.value}_")
    assert outputs._RUN_ID.pattern.startswith(rf"\A{IdKind.SCHEDULE_CPM_RUN.value}_")
    for kind in (IdKind.SCHEDULE_SCENARIO_VERSION, IdKind.SCHEDULE_CPM_RUN):
        identifier = f"{kind.value}_s62domain0001"
        pattern = (
            outputs._VERSION_ID if kind is IdKind.SCHEDULE_SCENARIO_VERSION else outputs._RUN_ID
        )
        assert pattern.fullmatch(identifier)
    # 164 at S6-2; Reports Modernization WP01 appended seven `gr*` kinds after.
    assert len(IdKind) == 171
    new = [
        IdKind.SCHEDULE_SCENARIO,
        IdKind.SCHEDULE_SCENARIO_VERSION,
        IdKind.SCHEDULE_CPM_RUN,
        IdKind.SCHEDULE_SCENARIO_OUTPUT,
        IdKind.SCHEDULE_SERIES_MATCH,
        IdKind.SCHEDULE_BASELINE,
        IdKind.SCHEDULE_BASELINE_EVENT,
        IdKind.SCHEDULE_GOVERNING_EVENT,
    ]
    assert list(IdKind)[156:164] == new
    for kind in new:
        others = [other.value for other in IdKind if other is not kind]
        assert not any(o.startswith(kind.value) or kind.value.startswith(o) for o in others), kind


# ---- enum lockstep (section 14.7.1) --------------------------------------------------


def test_the_retired_role_and_kind_are_gone() -> None:
    assert [member.value for member in SchedulePublicationRole] == ["update", "baseline"]
    assert {member.value for member in ScheduleBaselineKind} == {
        member.value for member in BaselineType
    }
    assert "reference" not in {member.value for member in SchedulePublicationRole}
    assert "working" not in {member.value for member in ScheduleBaselineKind}


# ---- the import request (section 14.7.2) ---------------------------------------------


def test_the_approval_record_is_bounded_and_normalized() -> None:
    ScheduleImportApproval("R" * 500, date(2026, 1, 1), "x" * 2000)
    for overrides in (
        {"approval_reference": ""},
        {"approval_reference": "R" * 501},
        {"approval_reference": " padded"},
        {"approval_reference": "two  spaces"},
        {"reason": ""},
        {"reason": "x" * 2001},
        {"reason": "trailing "},
        {"effective_from": "2026-01-01"},
    ):
        fields: dict[str, Any] = {
            "approval_reference": "Award letter",
            "effective_from": date(2026, 1, 1),
            "reason": "Synthetic",
            **overrides,
        }
        with pytest.raises(ValueError, match=r"."):
            ScheduleImportApproval(**fields)


def test_s5_requests_are_unchanged_by_the_defaults() -> None:
    request = _request()
    assert (request.series_auto, request.series_name_if_new, request.approval) == (
        False,
        None,
        None,
    )
    assert request.match_decision_id is None
    _request(series_id=SER, series_name=None)


@pytest.mark.parametrize(
    "overrides",
    [
        # Exactly one of `series_id`, `series_name`, `series_auto`.
        {"series_auto": True},
        {"series_auto": True, "series_name": None, "series_id": SER},
        {"series_name": None},
        {"series_auto": 1, "series_name": None},
        # `series_name_if_new` only with `series_auto`.
        {"series_name_if_new": normalize_series_name("New Series")},
        # `series_auto` is a plain update.
        {
            "series_auto": True,
            "series_name": None,
            "publication_role": SchedulePublicationRole.BASELINE,
            "baseline_kind": ScheduleBaselineKind.CONTRACT,
            "approval": APPROVAL,
        },
        {"series_auto": True, "series_name": None, "supersedes_publication_id": "spub_s62x0001"},
        {"series_auto": True, "series_name": None, "match_decision_id": DECISION},
        # `approval` set exactly on role `BASELINE`.
        {"approval": APPROVAL},
        {
            "publication_role": SchedulePublicationRole.BASELINE,
            "baseline_kind": ScheduleBaselineKind.CONTRACT,
        },
        # `match_decision_id`: a named Series, role update, no supersedes or approval.
        {"match_decision_id": DECISION, "supersedes_publication_id": "spub_s62x0001"},
        {
            "match_decision_id": DECISION,
            "publication_role": SchedulePublicationRole.BASELINE,
            "baseline_kind": ScheduleBaselineKind.CONTRACT,
            "approval": APPROVAL,
        },
        {"match_decision_id": "sser_s62domain0001"},
    ],
)
def test_import_request_scenario_invariants(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"."):
        _request(**overrides)


def test_import_request_scenario_forms_are_admitted() -> None:
    auto = _auto(series_name_if_new=normalize_series_name("  New   Series "))
    assert auto.series_name_if_new is not None and auto.series_name_if_new.key == "new series"
    assert _approved().approval == APPROVAL
    assert _request(match_decision_id=DECISION).match_decision_id == DECISION
    assert _request(series_id=SER, series_name=None, match_decision_id=DECISION)


# ---- the import digest (section 14.7.3) ----------------------------------------------

#: The S5b-1 golden of the same request shape (`v1`), recomputed independently.
_V1_BODY: Final = (
    b'{"principal_id":"prn_s62domain0001","request":{"baseline_kind":null,'
    b'"enrollment_id":"enr_s62domain0001","expected_data_date":"2026-05-04",'
    b'"project_id":"prj_s62domain0001","publication_role":"update",'
    b'"series_id":null,"series_name_key":"synthetic master schedule",'
    b'"source_object_id":"obj_s62domain0001","source_version_id":"ver_s62domain0001",'
    b'"supersedes_publication_id":null}}'
)
_GOLDEN_V1: Final = "f367a4a1c93cd3c5841ba7eccc9789cf514e07c9affbe0e7b4a79f1a979be4e5"
_GOLDEN_AUTO: Final = "6c42744fb12fd2f6119df5945c8abadcc6d8f5b325c920dd3f561b714bb7c62b"
_GOLDEN_APPROVAL: Final = "afe729f05498350c174a31f28c4f2ee2f3f4984d2851e1a54bffe1d5b51ea489"
_GOLDEN_SECOND: Final = "9f0b248260ec9b88e290cfaac32271175b20f871d21411841d18813f580ccd17"


def _v2(request: ScheduleImportRequest, **added: object) -> str:
    body = {
        "principal_id": P,
        "request": {
            "project_id": request.project_id,
            "series_id": request.series_id,
            "series_name_key": None if request.series_name is None else request.series_name.key,
            "enrollment_id": request.enrollment_id,
            "source_object_id": request.source_object_id,
            "source_version_id": request.source_version_id,
            "publication_role": request.publication_role.value,
            "baseline_kind": (
                None if request.baseline_kind is None else request.baseline_kind.value
            ),
            "expected_data_date": "2026-05-04",
            "supersedes_publication_id": None,
            "series_auto": False,
            "series_name_if_new_key": None,
            "approval_reference": None,
            "effective_from": None,
            "reason": None,
            "match_decision_id": None,
            **added,
        },
    }
    return hashlib.sha256(b"cpm-schedule-import-v2\n" + canonical_json_bytes(body)).hexdigest()


def test_v1_requests_keep_their_digest() -> None:
    """A request with no S6 field digests under `v1`, byte for byte (P2-45)."""
    digest = schedule_import_request_digest(P, _request())
    assert digest == hashlib.sha256(b"cpm-schedule-import-v1\n" + _V1_BODY).hexdigest()
    assert digest == _GOLDEN_V1


def test_v2_golden_vectors() -> None:
    auto = _auto(series_name_if_new=normalize_series_name("New Series"))
    assert schedule_import_request_digest(P, auto) == _GOLDEN_AUTO
    assert _v2(auto, series_auto=True, series_name_if_new_key="new series") == _GOLDEN_AUTO
    approved = _approved()
    assert schedule_import_request_digest(P, approved) == _GOLDEN_APPROVAL
    assert (
        _v2(
            approved,
            approval_reference="Contract award letter 7",
            effective_from="2026-06-01",
            reason="Synthetic approved baseline",
        )
        == _GOLDEN_APPROVAL
    )
    second = _request(series_id=SER, series_name=None, match_decision_id=DECISION)
    assert schedule_import_request_digest(P, second) == _GOLDEN_SECOND
    assert _v2(second, match_decision_id=DECISION) == _GOLDEN_SECOND


def test_v2_digest_binds_every_added_field() -> None:
    base = schedule_import_request_digest(P, _approved())
    for changed in (
        _approved(approval=ScheduleImportApproval("Other", date(2026, 6, 1), "Synthetic")),
        _approved(
            approval=ScheduleImportApproval("Contract award letter 7", date(2026, 6, 2), "x")
        ),
        _approved(baseline_kind=ScheduleBaselineKind.APPROVED_UPDATE),
    ):
        assert schedule_import_request_digest(P, changed) != base
    assert schedule_import_request_digest(P, _auto()) != schedule_import_request_digest(
        P, _auto(series_name_if_new=normalize_series_name("New Series"))
    )


# ---- plane.py (section 14.7.3) --------------------------------------------------------


def test_intake_series_name_and_key() -> None:
    digest = "0123456789abcdef" * 4
    name = plane.intake_series_name(digest)
    assert name.name == "Schedule intake 0123456789ab"
    assert plane.is_intake_name_key(name.key)
    assert not plane.is_intake_name_key(normalize_series_name("Master Schedule").key)
    assert plane.INTAKE_SERIES_PREFIX == "Schedule intake "


def test_second_admission_key() -> None:
    key = plane.second_admission_key(DECISION)
    assert key == hashlib.sha256(b"series-match-v1\n" + DECISION.encode("ascii")).hexdigest()
    assert re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key)
    assert plane.second_admission_key("ssmd_s62domain0002") != key


def test_writer_bucket() -> None:
    assert plane.writer_bucket("local_cli", None) is None
    assert plane.writer_bucket("local_web", None) is None
    assert plane.writer_bucket("local_unattested", None) == "local_unattested\x1f"
    assert plane.writer_bucket("remote_interactive", "client-7") == "remote_interactive\x1fclient-7"


def test_capability_sets_and_result_kinds() -> None:
    assert len(plane.PLANE_CLIENT_WRITE_CAPABILITIES) == 6
    assert len(plane.PLANE_OPERATOR_WRITE_CAPABILITIES) == 4
    assert not plane.PLANE_CLIENT_WRITE_CAPABILITIES & plane.PLANE_OPERATOR_WRITE_CAPABILITIES
    assert set(plane.RESULT_KIND_BY_CAPABILITY) == plane.PLANE_WRITE_CAPABILITIES
    assert set(plane.RESULT_KIND_BY_CAPABILITY.values()) == set(plane.PlaneResultKind)
    assert plane.MAX_CPM_RESULT_BYTES == 67_108_864
    assert plane.MATCH_INTEGRITY_REFUSAL == "integrity_violation"
    assert [member.value for member in plane.MatchAdmissionSkip] == ["plane_disabled"]
    assert MatchOutcome.ADMISSION_REFUSED.value == "admission_refused"


def test_provenance_sets_equal_the_lineage_sets() -> None:
    assert plane.PLANE_ATTESTED_DECISION_CHANNELS == lineage.ATTESTED_DECISION_CHANNELS
    assert plane.PLANE_CLIENT_DECISION_CHANNELS == lineage.CLIENT_DECISION_CHANNELS
    assert {member.value for member in lineage.AcceptanceBasis} == plane.PLANE_ACCEPTANCE_BASES
    assert plane.PLANE_AUTHORITY_CLASSES == lineage.ISSUE_AUTHORITY_CLASSES


@pytest.mark.parametrize(
    ("fields", "admitted"),
    [
        (("local_operator", "local_cli", None, "user_confirmed"), True),
        (("local_operator", "local_web", None, "user_confirmed"), True),
        (("ordinary_reviewer", "local_unattested", None, "client_identified"), True),
        (("ordinary_reviewer", "remote_interactive", "client-7", "client_identified"), True),
        (("local_operator", "local_unattested", None, "user_confirmed"), False),
        (("local_operator", "local_cli", "client-7", "user_confirmed"), False),
        (("local_operator", "local_cli", None, "client_identified"), False),
        (("ordinary_reviewer", "remote_interactive", None, "client_identified"), False),
        (("ordinary_reviewer", "local_unattested", "client-7", "client_identified"), False),
        (("ordinary_reviewer", "local_cli", None, "client_identified"), False),
        (("ordinary_reviewer", "remote_interactive", "c" * 257, "client_identified"), False),
        (("remote_operator_attested", "local_cli", None, "user_confirmed"), False),
    ],
)
def test_plane_provenance_follows_the_creator_rule(
    fields: tuple[str, str, str | None, str], admitted: bool
) -> None:
    if admitted:
        plane.PlaneProvenance(*fields)
    else:
        with pytest.raises(ValueError, match=r"."):
            plane.PlaneProvenance(*fields)


# ---- the lineage storage vocabulary (section 14.7.4) ---------------------------------

_S6_FAMILIES: Final = {
    "schedule_publication": IdKind.SCHEDULE_PUBLICATION,
    "schedule_activity": IdKind.SCHEDULE_ACTIVITY,
    "schedule_baseline": IdKind.SCHEDULE_BASELINE,
    "scenario": IdKind.SCHEDULE_SCENARIO,
    "scenario_version": IdKind.SCHEDULE_SCENARIO_VERSION,
    "scenario_output": IdKind.SCHEDULE_SCENARIO_OUTPUT,
}


def test_storage_vocabulary_is_the_public_vocabulary_plus_the_pending_s6_additions() -> None:
    """S6-2-D01: stored contains public, and stored minus public is exactly section 5.2's additions.

    S6-3 replaces this by equality when it widens the public enums and bumps
    the read generation to 2.
    """
    public_families = {
        family.value: kind for family, kind in lineage.RECORD_FAMILY_ID_KINDS.items()
    }
    stored_families = dict(lineage.STORED_RECORD_FAMILY_ID_KINDS)
    assert {k: stored_families[k] for k in public_families} == public_families
    assert {k: v for k, v in stored_families.items() if k not in public_families} == _S6_FAMILIES
    assert set(public_families) == {family.value for family in lineage.RecordFamily}
    public = {
        relation.value: (kind.value, {f.value for f in sources}, {f.value for f in targets})
        for relation, (kind, sources, targets) in lineage.RELATION_MATRIX.items()
    }
    stored = {
        relation: (kind, set(sources), set(targets))
        for relation, (kind, sources, targets) in lineage.STORED_RELATION_MATRIX.items()
    }
    assert set(stored) - set(public) == set(lineage.SCHEDULE_LINEAGE_RELATIONS)
    assert set(public) == {relation.value for relation in lineage.RelationType}
    widened = {"discusses", "originated_from"}
    for relation, (kind, sources, targets) in public.items():
        stored_kind, stored_sources, stored_targets = stored[relation]
        assert stored_kind == kind and sources <= stored_sources and targets <= stored_targets
        if relation not in widened:
            assert (stored_sources, stored_targets) == (sources, targets), relation
    assert stored["discusses"][2] - public["discusses"][2] == {
        "schedule_publication",
        "schedule_activity",
        "schedule_baseline",
        "scenario",
        "scenario_output",
    }
    assert stored["discusses"][1] == public["discusses"][1]
    assert stored["originated_from"][1] - public["originated_from"][1] == {
        "scenario_version",
        "schedule_baseline",
    }
    assert stored["originated_from"][2] == public["originated_from"][2]
    assert stored["concerns"] == (
        "semantic",
        {"scenario", "scenario_version", "scenario_output"},
        {"situation", "constraint", "task", "commitment", "schedule_activity", "schedule_baseline"},
    )
    assert stored["delays"] == ("semantic", {"constraint", "situation"}, {"schedule_activity"})
    assert stored["mitigates"] == (
        "semantic",
        {"task", "commitment", "scenario_version"},
        {"constraint", "situation"},
    )
    # The public read surface does not move in S6-2 (S6-2-D02).
    assert lineage.LINEAGE_READ_GENERATION == 1
    assert set(lineage.LINEAGE_FAMILY_READS) == set(lineage.RecordFamily)
