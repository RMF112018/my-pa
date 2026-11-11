"""Schedule Scenarios S6-3 package I10-B: the public lineage vocabulary (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` sections 5 and
15.11: the 6 Schedule families, the 3 relations, the widened relation matrix,
the 8 native virtual edges, the read grant map and the read generation 2; the
storage vocabulary the `record_links` CHECKs are built from equals the public
one (it replaces S6-2's superset pin); and the pure linkability, Baseline and
evidence rules of `application.lineage_endpoints`. Every value is synthetic.
"""

from __future__ import annotations

from typing import Final, cast

import pytest
from pydantic import ValidationError

from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.lineage_endpoints import (
    relation_kind,
    require_linkable,
    require_relation_evidence,
    require_schedule_relation,
)
from my_pa.application.record_lineage import _lineage_position
from my_pa.contracts.ports import IssueRepository, LineageEndpoint
from my_pa.contracts.v1.record_lineage import (
    LineageNodeView,
    LineagePathEdgeView,
    ScheduleBaselineNodeSummary,
    VirtualEdgeView,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.lineage import vocabulary as lineage
from my_pa.domain.lineage.cursor import scope_digest
from my_pa.domain.lineage.model import EvidenceAnchor, RecordRef
from my_pa.domain.lineage.vocabulary import (
    EvidenceRole,
    EvidenceSourceFamily,
    RecordFamily,
    RecordLinkKind,
    RelationType,
    SourceVersionKind,
)

#: Section 5.1: the 6 families and the identifier kind each carries.
_SCHEDULE_FAMILIES: Final = {
    "schedule_publication": IdKind.SCHEDULE_PUBLICATION,
    "schedule_activity": IdKind.SCHEDULE_ACTIVITY,
    "schedule_baseline": IdKind.SCHEDULE_BASELINE,
    "scenario": IdKind.SCHEDULE_SCENARIO,
    "scenario_version": IdKind.SCHEDULE_SCENARIO_VERSION,
    "scenario_output": IdKind.SCHEDULE_SCENARIO_OUTPUT,
}
#: Section 5.1: each family's read grant set.
_READS: Final = {
    "schedule_publication": {"schedule_publications.read", "schedule_publications.list"},
    "schedule_activity": {"schedule_activities.history", "schedule_activities.list"},
    "schedule_baseline": {"schedule_baselines.read", "schedule_baselines.list"},
    "scenario": {"schedule_scenarios.read", "schedule_scenarios.list"},
    "scenario_version": {"schedule_scenario_versions.read"},
    "scenario_output": {"schedule_scenario_outputs.read", "schedule_scenario_outputs.list"},
}
#: Section 5.2, spelled: the 3 new relations and the 2 widened ones.
_SECTION_5_2: Final = {
    "concerns": (
        "semantic",
        {"scenario", "scenario_version", "scenario_output"},
        {"situation", "constraint", "task", "commitment", "schedule_activity", "schedule_baseline"},
    ),
    "delays": ("semantic", {"constraint", "situation"}, {"schedule_activity"}),
    "mitigates": (
        "semantic",
        {"task", "commitment", "scenario_version"},
        {"constraint", "situation"},
    ),
}
_DISCUSSES_ADDED: Final = {
    "schedule_publication",
    "schedule_activity",
    "schedule_baseline",
    "scenario",
    "scenario_output",
}
_ORIGINATED_FROM_ADDED: Final = {"scenario_version", "schedule_baseline"}
_VIRTUAL_EDGES: Final = {
    "meeting_note_version_of",
    "scenario_version_of",
    "scenario_version_parent",
    "scenario_based_on_publication",
    "scenario_based_on_baseline",
    "scenario_forked_from_version",
    "scenario_output_of",
    "schedule_baseline_designates",
    "schedule_baseline_supersedes",
}


def _public_matrix() -> dict[str, tuple[str, set[str], set[str]]]:
    return {
        relation.value: (kind.value, {f.value for f in sources}, {f.value for f in targets})
        for relation, (kind, sources, targets) in lineage.RELATION_MATRIX.items()
    }


def test_storage_vocabulary_equals_the_public_vocabulary() -> None:
    """Section 15.11.1: stored = public, string-keyed, both directions (no revision needed)."""
    public_families = {
        family.value: kind for family, kind in lineage.RECORD_FAMILY_ID_KINDS.items()
    }
    stored_families = dict(lineage.STORED_RECORD_FAMILY_ID_KINDS)
    assert stored_families == public_families
    assert set(public_families) == {family.value for family in RecordFamily}
    stored = {
        relation: (kind, set(sources), set(targets))
        for relation, (kind, sources, targets) in lineage.STORED_RELATION_MATRIX.items()
    }
    assert stored == _public_matrix()
    assert set(stored) == {relation.value for relation in RelationType}
    assert dict(lineage.SCHEDULE_LINEAGE_FAMILY_ID_KINDS) == _SCHEDULE_FAMILIES


def test_the_public_vocabulary_is_section_5() -> None:
    """Sections 5.1, 5.2 and 15.11.1: 13 families, 11 relations, 9 edges, 13 read sets."""
    assert len(RecordFamily) == 13 and len(RelationType) == 11
    assert [family.value for family in RecordFamily][7:] == list(_SCHEDULE_FAMILIES)
    assert [relation.value for relation in RelationType][8:] == ["concerns", "delays", "mitigates"]
    assert {
        family.value: kind
        for family, kind in lineage.RECORD_FAMILY_ID_KINDS.items()
        if family in lineage.SCHEDULE_RECORD_FAMILIES
    } == _SCHEDULE_FAMILIES
    assert {family.value for family in lineage.SCHEDULE_RECORD_FAMILIES} == set(_SCHEDULE_FAMILIES)
    assert {
        family.value: set(reads)
        for family, reads in lineage.LINEAGE_FAMILY_READS.items()
        if family in lineage.SCHEDULE_RECORD_FAMILIES
    } == _READS
    assert set(lineage.LINEAGE_FAMILY_READS) == set(RecordFamily)
    assert {edge.value for edge in lineage.NativeVirtualEdge} == _VIRTUAL_EDGES
    public = _public_matrix()
    for relation, row in _SECTION_5_2.items():
        assert public[relation] == row, relation
    assert public["discusses"][2] >= _DISCUSSES_ADDED
    assert public["originated_from"][1] >= _ORIGINATED_FROM_ADDED
    assert set(_SECTION_5_2) == lineage.SCHEDULE_LINEAGE_RELATIONS
    # Contestable, not composite-only, not symmetric (section 5.2).
    added = {RelationType.CONCERNS, RelationType.DELAYS, RelationType.MITIGATES}
    assert added <= lineage.CONTESTABLE_RELATIONS and len(lineage.CONTESTABLE_RELATIONS) == 10
    assert not added & lineage.COMPOSITE_ONLY_RELATIONS
    # `issue_member` is not widened (S6-D12).
    assert not public["issue_member"][2] & set(_SCHEDULE_FAMILIES)


def test_lineage_generation_is_two() -> None:
    """Section 15.11.1 (S6-2-D02): generation 2, so a generation-1 cursor's scope never matches.

    Every lineage read compares a cursor's `s` with `scope_digest(...)` at the
    current generation and restarts on a mismatch (S3 section 5), so a
    generation-1 cursor -- local or remote -- is refused as a cursor.
    """
    assert lineage.LINEAGE_READ_GENERATION == 2
    assert scope_digest(None) == scope_digest(None, generation=2)
    assert scope_digest(None, generation=1) != scope_digest(None)
    assert scope_digest("a" * 64, generation=1) != scope_digest("a" * 64)


# ---- the pure rules of `application.lineage_endpoints` (section 15.11.2) ---------------


def _endpoint(family: RecordFamily, **facts: bool) -> LineageEndpoint:
    kind = lineage.RECORD_FAMILY_ID_KINDS[family]
    return LineageEndpoint(family=family, record_id=f"{kind.value}_unitlineage0001", **facts)


def _linkable(endpoint: LineageEndpoint) -> bool:
    try:
        # A Schedule endpoint never reaches the Issue repository.
        require_linkable(_issues(), "prn_unitlineage0001", endpoint)
    except InvalidRequestError as error:
        assert error.safe_details == (SafeDetail.ENDPOINT,)
        return False
    return True


def _issues() -> IssueRepository:
    """A stand-in no Schedule endpoint's check ever calls (any call would raise)."""
    return cast(IssueRepository, object())


@pytest.mark.parametrize("family", sorted(lineage.SCHEDULE_RECORD_FAMILIES))
def test_a_schedule_endpoint_is_linkable_only_when_its_row_says_so(family: RecordFamily) -> None:
    assert _linkable(_endpoint(family, schedule_linkable=True))
    assert not _linkable(_endpoint(family, schedule_linkable=False))


def test_originated_from_a_baseline_needs_an_approved_baseline() -> None:
    """RR1-F08: approval evidence only from an approved, unrevoked Baseline."""
    proposed = _endpoint(RecordFamily.SCHEDULE_BASELINE, schedule_linkable=True)
    approved = _endpoint(
        RecordFamily.SCHEDULE_BASELINE, schedule_linkable=True, baseline_approved=True
    )
    with pytest.raises(InvalidRequestError) as refused:
        require_schedule_relation(RelationType.ORIGINATED_FROM, proposed)
    assert refused.value.safe_details == (SafeDetail.RELATION_TYPE,)
    require_schedule_relation(RelationType.ORIGINATED_FROM, approved)
    # Every other relation and family is untouched by the rule.
    require_schedule_relation(RelationType.DISCUSSES, proposed)
    require_schedule_relation(
        RelationType.ORIGINATED_FROM,
        _endpoint(RecordFamily.SCENARIO_VERSION, schedule_linkable=True),
    )


def _ref(family: RecordFamily) -> RecordRef:
    kind = lineage.RECORD_FAMILY_ID_KINDS[family]
    return RecordRef(family=family, record_id=f"{kind.value}_unitlineage0001")


def _anchor(role: EvidenceRole) -> EvidenceAnchor:
    return EvidenceAnchor(
        source_family=EvidenceSourceFamily.CAPTURE_VERSION,
        source_root_id="cap_unitlineage0001",
        source_version_kind=SourceVersionKind.IMMUTABLE_VERSION,
        source_version_id="capver_unitlineage0001",
        source_version_no=1,
        source_sha256="0" * 64,
        passage_start_cp=None,
        passage_end_cp=None,
        passage_sha256=None,
        role=role,
    )


@pytest.mark.parametrize(
    ("relation", "from_family", "to_family"),
    [
        (RelationType.DELAYS, RecordFamily.CONSTRAINT, RecordFamily.SCHEDULE_ACTIVITY),
        (RelationType.MITIGATES, RecordFamily.SCENARIO_VERSION, RecordFamily.SITUATION),
    ],
)
def test_delays_and_mitigates_need_an_exact_corroborating_anchor(
    relation: RelationType, from_family: RecordFamily, to_family: RecordFamily
) -> None:
    """Section 15.11.2: `delays` and `mitigates` need >= 1 exact-version `corroborates` anchor."""
    from_ref, to_ref = _ref(from_family), _ref(to_family)
    assert relation_kind(relation, from_ref, to_ref) is RecordLinkKind.SEMANTIC
    for anchors in ((), (_anchor(EvidenceRole.CONTRADICTS),)):
        with pytest.raises(InvalidRequestError) as refused:
            require_relation_evidence(relation, from_ref, to_ref, anchors)
        assert refused.value.safe_details == (SafeDetail.EVIDENCE_ANCHORS,)
    require_relation_evidence(relation, from_ref, to_ref, (_anchor(EvidenceRole.CORROBORATES),))


def test_concerns_needs_no_evidence_and_refuses_an_unadmitted_pair() -> None:
    scenario, activity = _ref(RecordFamily.SCENARIO), _ref(RecordFamily.SCHEDULE_ACTIVITY)
    require_relation_evidence(RelationType.CONCERNS, scenario, activity, ())
    assert relation_kind(RelationType.CONCERNS, scenario, activity) is RecordLinkKind.SEMANTIC
    with pytest.raises(InvalidRequestError) as refused:
        relation_kind(RelationType.CONCERNS, activity, scenario)
    assert refused.value.safe_details == (SafeDetail.RELATION_TYPE,)


# ---- read shapes (section 15.11.3a; package I10-C) ----------------------------------------

#: Section 15.11.3a item 2: the 9 endpoint pairs, exact.
_ENDPOINTS: Final = {
    "meeting_note_version_of": ("meeting_note_version", "meeting"),
    "scenario_version_of": ("scenario_version", "scenario"),
    "scenario_version_parent": ("scenario_version", "scenario_version"),
    "scenario_based_on_publication": ("scenario", "schedule_publication"),
    "scenario_based_on_baseline": ("scenario", "schedule_baseline"),
    "scenario_forked_from_version": ("scenario", "scenario_version"),
    "scenario_output_of": ("scenario_output", "scenario_version"),
    "schedule_baseline_designates": ("schedule_baseline", "schedule_publication"),
    "schedule_baseline_supersedes": ("schedule_baseline", "schedule_baseline"),
}


def _identifier(family: str) -> str:
    """A synthetic, well-formed identifier of `family`."""
    kind = lineage.RECORD_FAMILY_ID_KINDS[RecordFamily(family)]
    return validate_identifier(f"{kind.value}_s63fast0001", kind)


def _ref_document(family: str) -> dict[str, str]:
    return {"family": family, "record_id": _identifier(family)}


def test_virtual_edge_endpoint_table_is_exact() -> None:
    """Item 2 (P3-55 run 1): the table, and `VirtualEdgeView` admits exactly its pairs."""
    assert {
        edge.value: (pair[0].value, pair[1].value)
        for edge, pair in lineage.NATIVE_VIRTUAL_EDGE_ENDPOINTS.items()
    } == _ENDPOINTS
    families = [family.value for family in RecordFamily]
    for edge, pair in _ENDPOINTS.items():
        for source in families:
            for target in families:
                document = {"edge_type": edge, "from_ref": _ref_document(source), "to_ref": _ref_document(target)}
                if (source, target) == pair:
                    view = VirtualEdgeView.model_validate(document)
                    assert view.to_canonical_dict()["from"]["family"] == source
                else:
                    with pytest.raises(ValidationError):
                        VirtualEdgeView.model_validate(document)


def test_virtual_path_step_admits_only_the_note_edge() -> None:
    """Item 3 (P3-55 run 2): a Schedule edge is never a path step."""
    for edge in lineage.NativeVirtualEdge:
        document = {"edge": "virtual", "edge_type": edge.value}
        if edge is lineage.NativeVirtualEdge.MEETING_NOTE_VERSION_OF:
            assert LineagePathEdgeView.model_validate(document).to_canonical_dict() == document
        else:
            with pytest.raises(ValidationError):
                LineagePathEdgeView.model_validate(document)


_SUMMARIES: Final[dict[str, dict[str, object]]] = {
    "schedule_publication": {
        "data_class": "schedule_publication",
        "authority": "source_bound_derived",
        "authoritative": False,
        "reportable": False,
        "trust": "source_bound_derived",
        "data_date": "2026-05-04",
        "status": "complete",
        "series_kind": "standard",
    },
    "schedule_activity": {
        "data_class": "schedule_activity",
        "authority": "source_bound_derived",
        "authoritative": False,
        "reportable": False,
        "trust": "source_bound_derived",
        "published_activity_id": "A100",
    },
    "schedule_baseline": {
        "data_class": "schedule_baseline",
        "authority": "proposed",
        "authoritative": False,
        "reportable": False,
        "trust": "model_proposed",
        "status": "proposed",
        "label": None,
        "effective_type": None,
    },
    "scenario": {
        "data_class": "schedule_scenario",
        "authority": "client_authored",
        "authoritative": False,
        "reportable": False,
        "trust": "model_proposed",
        "origin_kind": "publication",
    },
    "scenario_version": {
        "data_class": "schedule_scenario",
        "authority": "client_authored",
        "authoritative": False,
        "reportable": False,
        "trust": "model_proposed",
        "version_no": 2,
        "version_label": "what_if",
    },
    "scenario_output": {
        "data_class": "schedule_scenario_output",
        "authority": "client_asserted",
        "authoritative": False,
        "reportable": False,
        "trust": "model_proposed",
        "kind": "monte_carlo",
        "iterations": 1000,
    },
}


def _node(family: str, schedule: dict[str, object] | None) -> dict[str, object]:
    document: dict[str, object] = {
        "family": family,
        "record_id": _identifier(family),
        "depth": 0,
    }
    if family == "meeting_note_version":
        document["meeting_id"] = _identifier("meeting")
    if family == "situation":
        document |= {"title": "Synthetic", "state": "open"}
    if family == "capture_version":
        document["availability"] = "available"
    if schedule is not None:
        document["schedule"] = schedule
    return document


@pytest.mark.parametrize("family", [family.value for family in RecordFamily])
def test_node_schedule_key_is_present_iff_schedule_family(family: str) -> None:
    """Item 1 (R10-S03): the key iff a Schedule family, its exact model, `null`s kept."""
    summary = _SUMMARIES.get(family)
    if summary is None:
        node = LineageNodeView.model_validate(_node(family, None))
        assert "schedule" not in node.to_canonical_dict()
        with pytest.raises(ValidationError):
            LineageNodeView.model_validate(_node(family, _SUMMARIES["scenario"]))
        return
    node = LineageNodeView.model_validate(_node(family, summary))
    assert node.to_canonical_dict()["schedule"] == summary
    # Missing, extra, a wrong label, or another family's summary are refused.
    with pytest.raises(ValidationError):
        LineageNodeView.model_validate(_node(family, None))
    for broken in (
        {**summary, "name": "Synthetic"},
        {key: value for key, value in summary.items() if key != "trust"},
        {**summary, "reportable": True},
    ):
        with pytest.raises(ValidationError):
            LineageNodeView.model_validate(_node(family, broken))
    for other, other_summary in _SUMMARIES.items():
        if other != family and set(other_summary) != set(summary):
            with pytest.raises(ValidationError):
                LineageNodeView.model_validate(_node(family, other_summary))


def test_a_baseline_summary_labels_by_its_effective_type() -> None:
    """Item 1 (R10-S02): `operator_approved` iff an effective type; authoritative iff approved."""
    revoked = {
        **_SUMMARIES["schedule_baseline"],
        "authority": "operator_approved",
        "status": "revoked",
        "label": "BL-1",
        "effective_type": "contract",
    }
    assert ScheduleBaselineNodeSummary.model_validate(revoked).authoritative is False
    for broken in (
        {**revoked, "authority": "proposed"},
        {**revoked, "authoritative": True},
        {**_SUMMARIES["schedule_baseline"], "authority": "operator_approved"},
    ):
        with pytest.raises(ValidationError):
            ScheduleBaselineNodeSummary.model_validate(broken)


@pytest.mark.parametrize(
    ("position", "admitted"),
    [
        ("v:" + _identifier("meeting_note_version"), True),
        (
            "v:scenario_version_of:scenario_version:"
            + _identifier("scenario_version")
            + ":scenario:"
            + _identifier("scenario"),
            True,
        ),
        # A mismatched family pair, the note edge in the long form, a bad id.
        (
            "v:scenario_version_of:scenario:"
            + _identifier("scenario")
            + ":scenario_version:"
            + _identifier("scenario_version"),
            False,
        ),
        (
            "v:meeting_note_version_of:meeting_note_version:"
            + _identifier("meeting_note_version")
            + ":meeting:"
            + _identifier("meeting"),
            False,
        ),
        ("v:scenario_version_of:scenario_version:sscv_x:scenario:sscn_x", False),
        ("v:scenario_version_of:scenario_version", False),
    ],
)
def test_lineage_position_admits_the_schedule_edge_key(position: str, admitted: bool) -> None:
    """Item 5 (R10-T01): the cursor position grammar, amended for Schedule edges."""
    assert _lineage_position(position) is admitted
