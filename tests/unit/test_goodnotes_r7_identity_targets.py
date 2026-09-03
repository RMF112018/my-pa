import pytest

from my_pa.application.goodnotes_delivery import resolve_typed_identity_candidate
from my_pa.domain.goodnotes.models import (
    GoodNotesEntityResolution,
    GoodNotesIdentityCandidate,
    GoodNotesIdentityDirectoryRecord,
    GoodNotesIdentityTargetKind,
)
from my_pa.domain.relationship import EntityType

DIRECTORY = (
    GoodNotesIdentityDirectoryRecord(
        target_id="ent_aaaaaaaaaaaaaaaa",
        target_kind=GoodNotesIdentityTargetKind.PERSON,
        normalized_name="alex rivera",
        entity_type=EntityType.PERSON,
    ),
    GoodNotesIdentityDirectoryRecord(
        target_id="ent_bbbbbbbbbbbbbbbb",
        target_kind=GoodNotesIdentityTargetKind.ORGANIZATION,
        normalized_name="acme builders",
        entity_type=EntityType.ORGANIZATION,
    ),
    GoodNotesIdentityDirectoryRecord(
        target_id="prj_cccccccccccccccc",
        target_kind=GoodNotesIdentityTargetKind.PROJECT,
        normalized_name="alpha project",
    ),
)


@pytest.mark.parametrize(
    ("literal", "target_kind", "expected_id"),
    (
        ("Alex Rivera", GoodNotesIdentityTargetKind.PERSON, "ent_aaaaaaaaaaaaaaaa"),
        (
            "ent_aaaaaaaaaaaaaaaa",
            GoodNotesIdentityTargetKind.PERSON,
            "ent_aaaaaaaaaaaaaaaa",
        ),
        ("Acme Builders", GoodNotesIdentityTargetKind.ORGANIZATION, "ent_bbbbbbbbbbbbbbbb"),
        ("Alpha Project", GoodNotesIdentityTargetKind.PROJECT, "prj_cccccccccccccccc"),
    ),
)
def test_r7_typed_candidate_resolves_only_within_its_bound_target_kind(
    literal: str,
    target_kind: GoodNotesIdentityTargetKind,
    expected_id: str,
) -> None:
    candidate = GoodNotesIdentityCandidate(
        literal=literal,
        target_kind=target_kind,
        confidence=0.91,
        evidence_refs=("gnver_aaaaaaaaaaaaaaaaaaaaaaaa",),
    )
    result = resolve_typed_identity_candidate(candidate, DIRECTORY)
    assert result.resolution is GoodNotesEntityResolution.ASSOCIATED
    assert result.resolved_id == expected_id
    assert result.candidate is candidate


def test_r7_mismatched_ambiguous_and_missing_targets_preserve_review_evidence() -> None:
    candidate = GoodNotesIdentityCandidate(
        literal="Alex Rivera",
        target_kind=GoodNotesIdentityTargetKind.ORGANIZATION,
        confidence=0.42,
        evidence_refs=("segment:left",),
    )
    result = resolve_typed_identity_candidate(candidate, DIRECTORY)
    assert result.resolution is GoodNotesEntityResolution.UNRESOLVED
    assert result.resolved_id is None
    assert result.candidate.literal == "Alex Rivera"
    assert result.candidate.confidence == 0.42
    assert result.candidate.evidence_refs == ("segment:left",)

    duplicate = GoodNotesIdentityDirectoryRecord(
        target_id="ent_dddddddddddddddd",
        target_kind=GoodNotesIdentityTargetKind.PERSON,
        normalized_name="alex rivera",
        entity_type=EntityType.PERSON,
    )
    ambiguous = resolve_typed_identity_candidate(
        GoodNotesIdentityCandidate(
            literal="Alex Rivera", target_kind=GoodNotesIdentityTargetKind.PERSON
        ),
        (*DIRECTORY, duplicate),
    )
    assert ambiguous.resolution is GoodNotesEntityResolution.UNRESOLVED


def test_r7_directory_contract_rejects_wrong_identity_planes() -> None:
    with pytest.raises(ValueError, match="expected 'ent' identifier"):
        GoodNotesIdentityDirectoryRecord(
            target_id="per_aaaaaaaaaaaaaaaa",
            target_kind=GoodNotesIdentityTargetKind.PERSON,
            normalized_name="legacy person",
            entity_type=EntityType.PERSON,
        )
    with pytest.raises(ValueError, match="expected 'prj' identifier"):
        GoodNotesIdentityDirectoryRecord(
            target_id="ent_aaaaaaaaaaaaaaaa",
            target_kind=GoodNotesIdentityTargetKind.PROJECT,
            normalized_name="entity project",
        )
    with pytest.raises(ValueError, match="agree with the candidate target"):
        GoodNotesIdentityDirectoryRecord(
            target_id="ent_aaaaaaaaaaaaaaaa",
            target_kind=GoodNotesIdentityTargetKind.PERSON,
            normalized_name="wrong type",
            entity_type=EntityType.ORGANIZATION,
        )
    with pytest.raises(ValueError, match="normalized identity name must be canonical"):
        GoodNotesIdentityDirectoryRecord(
            target_id="ent_aaaaaaaaaaaaaaaa",
            target_kind=GoodNotesIdentityTargetKind.PERSON,
            normalized_name=" Alex  Rivera ",
            entity_type=EntityType.PERSON,
        )


@pytest.mark.parametrize(
    ("literal", "target_kind"),
    (
        ("ent_eeeeeeeeeeeeeeee", GoodNotesIdentityTargetKind.PERSON),
        ("prj_eeeeeeeeeeeeeeee", GoodNotesIdentityTargetKind.PERSON),
        ("ent_eeeeeeeeeeeeeeee", GoodNotesIdentityTargetKind.PROJECT),
        ("prj_eeeeeeeeeeeeeeee", GoodNotesIdentityTargetKind.PROJECT),
    ),
)
def test_r7_id_shaped_literals_never_fall_back_to_name_matching(
    literal: str, target_kind: GoodNotesIdentityTargetKind
) -> None:
    deceptive = (
        GoodNotesIdentityDirectoryRecord(
            target_id="ent_dddddddddddddddd",
            target_kind=GoodNotesIdentityTargetKind.PERSON,
            normalized_name=literal,
            entity_type=EntityType.PERSON,
        ),
        GoodNotesIdentityDirectoryRecord(
            target_id="prj_dddddddddddddddd",
            target_kind=GoodNotesIdentityTargetKind.PROJECT,
            normalized_name=literal,
        ),
    )
    result = resolve_typed_identity_candidate(
        GoodNotesIdentityCandidate(literal=literal, target_kind=target_kind), deceptive
    )
    assert result.resolution is GoodNotesEntityResolution.UNRESOLVED
    assert result.resolved_id is None
